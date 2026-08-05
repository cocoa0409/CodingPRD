# Community-Association Collections & Lien API — Product Requirements Document

## 1. Introduction

Community associations — homeowner associations and condominium boards — depend on the timely collection of assessments to fund shared operations. When an owner falls behind, the association's managing agent must run a tightly regulated collection process that threads federal consumer-protection law (the FDCPA), state lien and foreclosure statutes, bankruptcy stays, and strict trust-accounting rules. A misstep — sending a demand while a dispute is open, recording a lien before the validation window has run, remitting funds the trust does not hold — exposes the agent and the association to statutory liability.

This API is the system of record for that collection lifecycle. It tracks each delinquent account from its first overdue charge through notice-and-demand, payment-plan negotiation, lien recording, foreclosure referral, and — where it arises — bankruptcy, while continuously reconciling the cash held in trust against what is owed to each association. Every monetary movement is captured to the cent, every state change is gated by the compliance rule that governs it, and every legal escalation is subject to a maker-checker separation of duties. The design goal is that no reachable sequence of API calls can produce an FDCPA-noncompliant action, an out-of-trust remittance, or a lien recorded on an account that does not qualify.

A logical clock drives all time-dependent computation — aging, validation-period elapse, notice cooldowns, and payoff projection — so that the collection timeline can be exercised deterministically rather than against wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting an `X-User-Role` that is not one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A syntactically authenticated request that attempts an operation its role is not permitted to perform is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes four roles:

- **`CollectionsAgent`** — the day-to-day collections operator. Onboards associations and accounts, posts assessments, records payments and reversals, drafts and transitions FDCPA notices, and manages payment plans.
- **`ComplianceOfficer`** — the legal-escalation authority. Records liens, refers and advances foreclosures, records and resolves bankruptcy cases, and charges-off/closes accounts.
- **`TrustAccountant`** — the trust-accounting authority. Drafts and executes remittances of collected funds to associations, net of the management fee.
- **`AssociationManager`** — the association's own manager (a client), with read-only access scoped to its own association.

`CollectionsAgent`, `ComplianceOfficer`, and `TrustAccountant` are opaque operator identities: when `X-User-Role` is any of these, `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it where a scaffold transition writes it — for example, as `recorded_by_user_id` on a `Lien` or `referred_by_user_id` on a `ForeclosureReferral` — but it does not compare it to any entity's `id`.

`AssociationManager` is entity-backed by `Association`: when `X-User-Role` is `AssociationManager`, `X-User-ID` is the `id` of the acting `Association`. Ownership checks on any resource compare the resource's owning `association_id` to `X-User-ID`; an `AssociationManager` reading an association, an account (or its child assessments, payments, notices, plans, liens, referrals, and bankruptcy cases), an aging report, a payoff quote, or a remittance that does not belong to its own association is rejected with `ERR_UNAUTHORIZED`. For a child resource, ownership resolves through the parent `Account` to its `association_id`.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

### 2.3. Pagination

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, may be no smaller than 1 and no larger than 100. The `offset` defaults to 0 and represents the number of leading records to skip. Results are always ordered by `created_at` ascending. The `meta` block of a list response carries `limit`, `offset`, `total_count` (the total number of records matching the filter, ignoring pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Common Resource Properties, Identifiers, and the Logical Clock

Every persisted resource carries a server-minted `id` — an opaque UUID with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits stamped from the logical clock at creation. All entities in this system (`Association`, `Account`, `Assessment`, `Payment`, `Notice`, `PaymentPlan`, `Lien`, `ForeclosureReferral`, `BankruptcyCase`, and `Remittance`) additionally carry an `updated_at` timestamp and an integer `version`. The `version` begins at 1 on creation and increments by 1 on every mutation of the resource; `updated_at` is refreshed to the current logical-clock instant whenever the resource changes.

Only `created_at`, `updated_at`, and `api_request_timestamp` are rendered with three fractional digits. Every other server-generated domain instant that is stamped or computed from the logical clock — a notice's `sent_date` and `dispute_date`, a payment plan's computed `final_due_date`, a lien's `recorded_date`, a foreclosure referral's `referred_date`, and a payoff quote's `quote_date` and `good_through_date` — is rendered in plain-second ISO 8601 UTC form, `YYYY-MM-DDTHH:MM:SSZ`, with no fractional digits. Client-supplied date/instant inputs (for example `due_date`, `received_date`, `filed_date`, `first_due_date`, `period_start`, and `period_end`) are echoed back verbatim as received.

The server maintains a single **logical clock** that supplies "now" for every time-dependent computation — aging, notice cooldowns, the FDCPA validation period, plan-breach evaluation, and payoff projection all read it. Its startup default is `2026-05-01T00:00:00Z`; before any clock-setting call the clock reads exactly this default and never falls back to wall-clock time. An operator may advance the clock to a supplied instant; the new value is provided as `to_iso8601`.

When a nested resource is addressed, path parameters are validated left to right, and every foreign-key body field is validated for existence as well; any path id or referenced FK id that does not resolve to a live resource yields `ERR_NOT_FOUND` (HTTP 404).

### 2.5. Monetary Precision and Rounding

All monetary quantities are stored and returned as integer **cents**; aggregations of cents (balances, trust totals, gross and net remittance amounts) are exact. Where a percentage produces a fractional cent — interest accrual on a payoff quote, and the management fee on a remittance — the value is computed to two decimal places internally and then rounded **half up** to a whole cent. Two rules recur and matter: interest is rounded half-up **per assessment** before the per-assessment results are summed, and the management fee is rounded half-up **per payment** before the per-payment results are summed. Rounding is never deferred to the aggregate.

### 2.6. Optimistic Concurrency Control

Two create operations are guarded by optimistic concurrency against a parent resource's `version`.

A payment-plan create must carry `expected_account_version`, the client's last observed `version` of the target `Account`. If it does not equal the account's current `version` — because another writer has since posted a payment, recorded a lien, or drafted a superseding plan and thereby advanced the account — the create is refused with `ERR_STALE_VERSION` (HTTP 412) rather than overwriting a state the client never saw. A successful create increments the account's `version` by 1.

A remittance create must carry `expected_association_version`, the client's last observed `version` of the target `Association`. If it does not equal the association's current `version` — because another writer has changed the trust position, for example by posting a payment or remitting a prior remittance — the create is refused with `ERR_STALE_VERSION` (HTTP 412). A successful create increments the association's `version` by 1. No other endpoint accepts a version field.

### 2.7. Validation Ordering and Error Precedence

When a single request could fail multiple checks, the checks are evaluated in a fixed priority order and the first failure determines the error returned:

1. **Authentication** — headers present and `X-User-Role` known, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role may perform the operation, and an `AssociationManager` acts only within its own `association_id`, else `ERR_UNAUTHORIZED` (403).
3. **Separation of duties** — on a foreclosure referral, the acting `X-User-ID` differs from the recorder of the referenced lien, else `ERR_SEGREGATION_OF_DUTIES` (403).
4. **Existence** — all path ids and FK body ids resolve, else `ERR_NOT_FOUND` (404).
5. **Optimistic concurrency** — `expected_account_version` / `expected_association_version` match on the OCC-guarded creates, else `ERR_STALE_VERSION` (412).
6. **State validity** — the target resource is in a state that admits the requested transition or action, else `ERR_INVALID_STATE` (409).
7. **Automatic bankruptcy stay** — while the account is in `BANKRUPTCY`, no lien recording, foreclosure referral or advance, or notice send is permitted, else `ERR_AUTOMATIC_STAY` (403).
8. **FDCPA dispute pause** — while any notice on the account is `DISPUTED`, lien recording and foreclosure referral are blocked, else `ERR_ACTIVE_DISPUTE` (409).
9. **Predecessor existence** — the required predecessor resource exists (checked *before* any temporal elapse test), else `ERR_DEMAND_NOTICE_REQUIRED` or `ERR_LIEN_REQUIRED` (409).
10. **Validation-period elapse** — the FDCPA validation period has run since the intent-to-lien notice was sent, else `ERR_VALIDATION_PERIOD_ACTIVE` (409).
11. **Interval overlap** — a new plan's date interval does not overlap a live plan (`ERR_PLAN_OVERLAP`, 409) and a notice send does not collide with an active same-type cooldown (`ERR_NOTICE_COOLDOWN`, 409).
12. **Lien minimum** — the account balance meets the lien-recording minimum, else `ERR_LIEN_MINIMUM_NOT_MET` (422).
13. **Monetary validity** — assessment, payment, and plan amounts are positive, else `ERR_INVALID_AMOUNT` (422).
14. **Remittance period validity** — the remittance period end is not before its start, else `ERR_PERIOD_INVALID` (422).
15. **Enum membership** — every enum input carries a declared member, else `ERR_INVALID_ENUM` (422).
16. **Presence and typing** — every required input field is present and well-typed, else `ERR_VALIDATION` (422).

Note that the separation-of-duties check (3), stale-version check (5), and the bankruptcy stay (7) all precede the temporal and threshold checks, so, for example, a lien recording attempted on an account under an active bankruptcy is stopped by the stay before the validation-period or minimum-balance gates are ever evaluated.

### 2.8. State Cascades and the Conservation of Trust Cash

Many state changes in this domain propagate. When an operation mutates more than one resource, every affected resource has its `updated_at` refreshed and its `version` incremented, and all effects are applied atomically within the triggering request. The concrete cascades — foreclosure completion waiving open charges, a bankruptcy filing staying liens and referrals and suspending plans, a payment reversal reopening assessments — are described with the workflows that trigger them in §3.

Two quantities are **conserved** and must reconcile at all times. First, an account's `total_balance_cents` always equals the sum of the unpaid remainders of its live charges; every allocation, reversal, and waiver recomputes it. Second, an association's `trust_balance_cents` equals the total of all posted payment amounts on its accounts minus the total gross of all executed remittances; because a payment reversal removes exactly what the posting added, a post-then-reverse pair nets to zero change in trust cash.

## 3. Business Logic & Workflows

### 3.1. Associations and the Account Delinquency Lifecycle

A `CollectionsAgent` onboards a community association by supplying its legal `name` and the two-letter `state_code` that governs the applicable FDCPA and lien statutes. Three economic parameters may be supplied or left to default: the annual simple-interest rate on delinquent principal, `interest_rate_annual_pct` (default 12.0 percent); the flat late fee, `late_fee_cents` (default 2500); and the collections management fee, `management_fee_pct` (default 20.0 percent), applied per remittance. A newly created association starts with a `trust_balance_cents` of zero. Its computed `trust_balance_cents` is exposed on every read.

The agent then opens a delinquent-collections account against an association by supplying the `association_id`, the `unit_number` (the lot or unit identifier), and the delinquent `owner_name` — who is also the FDCPA consumer. A new account begins in `CURRENT` with a `total_balance_cents` of zero. Accounts may be listed and optionally filtered by their owning association or by their collection stage; each account read also carries its computed `aging` breakdown.

An account's `status` walks a collection-stage state machine over the values `CURRENT`, `DELINQUENT`, `PAYMENT_PLAN`, `LIEN`, `FORECLOSURE`, `BANKRUPTCY`, `CHARGED_OFF`, and `CLOSED`. Two transitions are driven manually by an operator; the rest are consequences of other events described throughout this section. A `CollectionsAgent` may mark a `CURRENT` account `DELINQUENT`, but only when the account actually owes money — its `total_balance_cents` must be greater than zero (otherwise `ERR_INVALID_AMOUNT`) and at least one assessment must be in `OPEN` or `PARTIAL` with a `due_date` at or before the logical-clock now (otherwise `ERR_NOT_DELINQUENT`). The same agent may close a `CURRENT` account, but only when its `total_balance_cents` is exactly zero and the account carries no lien in `RECORDED`, `STAYED`, or `FORECLOSING` and no foreclosure referral outside a terminal state; a violation of either condition yields `ERR_INVALID_STATE`. A `ComplianceOfficer`, separately, may close a `CHARGED_OFF` account, provided no bankruptcy case on it is still `FILED`, else `ERR_INVALID_STATE`. Any attempt to drive the account directly into one of the system-managed statuses via the manual transition is rejected with `ERR_INVALID_STATE`.

Whenever a payment allocation drives an account's `total_balance_cents` to zero, the system returns the account to `CURRENT`: a `DELINQUENT → CURRENT` transition, or a `LIEN → CURRENT` transition that additionally releases the `RECORDED` lien on the account (see §3.6).

### 3.2. Charges, Balances, and Aging

A charge against an account is an **assessment**. A `CollectionsAgent` posts one by supplying the `account_id`, the `charge_type`, the `amount_cents`, and the `due_date`. The `charge_type` is one of `REGULAR`, `SPECIAL`, `LATE_FEE`, `INTEREST`, `ATTORNEY_COST`, or `FINE`, and `amount_cents` must be greater than zero, else `ERR_INVALID_AMOUNT`. A new assessment opens in `OPEN` with its computed `balance_cents` initialized equal to `amount_cents`. As payments are applied, `balance_cents` falls; the assessment's `status` moves through `OPEN`, `PARTIAL`, `PAID`, and `WAIVED`.

An account's `total_balance_cents` is, at every instant, the sum of `balance_cents` across that account's assessments whose `status` is `OPEN` or `PARTIAL`; assessments in `PAID` or `WAIVED` are excluded. This aggregate is recomputed on every assessment change, payment allocation, reversal, and waiver.

A `CollectionsAgent` may **waive** an `OPEN` or `PARTIAL` assessment — a compensating action for a charge that should not have been levied. Waiving drives the assessment's `balance_cents` to zero, moves it to `WAIVED`, and recomputes the account's `total_balance_cents`.

**Aging.** Each account exposes an `aging` object bucketing unpaid balances by how overdue they are at the logical-clock now. For every assessment in `OPEN` or `PARTIAL`, the whole-day count is the floor of (now minus `due_date`) in days, and is negative for a charge not yet due. A charge with a day count of zero or less contributes to `bucket_current`; from 1 through 30 days to `bucket_1_30`; from 31 through 60 to `bucket_31_60`; from 61 through 90 to `bucket_61_90`; and 91 or more to `bucket_91_plus`. The boundaries at 30, 60, and 90 are inclusive on the lower bucket. The association-level aging report aggregates these across all of the association's accounts, returning `association_id`, the total delinquent cents as `total_delinquent_cents`, the five buckets as `bucket_current_cents`, `bucket_1_30_cents`, `bucket_31_60_cents`, `bucket_61_90_cents`, and `bucket_91_plus_cents`, and the number of accounts as `account_count`. (The delinquency grace period underlying the current bucket is 30 days.)

### 3.3. Payments, the Allocation Waterfall, and Reversals

A `CollectionsAgent` records a payment by supplying the `account_id`, the `amount_cents` (which must be greater than zero, else `ERR_INVALID_AMOUNT`), and the `received_date` on which funds arrived — the date that later governs which remittance period the payment falls in. A recorded payment posts immediately in `POSTED` and runs the **allocation waterfall**.

The waterfall considers the account's assessments in `OPEN` or `PARTIAL` and applies the payment against them in a fully pinned order. Assessments are ordered first by `charge_type` priority — `ATTORNEY_COST` first, then `FINE`, then `LATE_FEE`, then `INTEREST`, then `SPECIAL`, and `REGULAR` last — then, within the same charge type, by `due_date` ascending, and finally by `created_at` ascending; the resource `id` is never used as a tiebreaker. Walking that order, the system applies to each assessment the smaller of the remaining payment and that assessment's `balance_cents`, records the applied amount, decrements the assessment's `balance_cents`, and marks the assessment `PAID` when its balance reaches zero or `PARTIAL` otherwise. Allocation stops once the payment is exhausted. Each application is captured in the payment's `allocations` array as an entry pairing the `assessment_id` with the `applied_cents`; any amount left after all live charges are satisfied is retained as the payment's `unapplied_cents` (an overpayment credit, which may be zero). If the account has no `OPEN` or `PARTIAL` assessment, the entire amount becomes `unapplied_cents`.

Posting a payment increases the association's `trust_balance_cents` by the payment's `amount_cents`, recomputes the account's `total_balance_cents`, and — if that balance reaches zero — returns the account to `CURRENT` through the system transitions of §3.1.

A payment may be **reversed** for a stated `reversal_reason` of `NSF` or `ADJUSTMENT`. Reversal is permitted only on a payment currently in `POSTED`; reversing an already-`REVERSED` payment yields `ERR_INVALID_STATE`. Reversal un-applies every allocation: each target assessment's `balance_cents` is restored by the amount that had been applied, and its `status` reverts accordingly — `PAID` back to `PARTIAL` when the restoration is partial or to `OPEN` when fully restored, and `PARTIAL` back to `OPEN` when fully restored. The account's `total_balance_cents` is recomputed; if it becomes greater than zero and the account had been returned to `CURRENT` by this very payment, the account moves back to `DELINQUENT`. Finally, the association's `trust_balance_cents` is decreased by the payment's `amount_cents`, so that the post-and-reverse pair leaves trust cash unchanged.

### 3.4. FDCPA Notices, Demands, and Disputes

Collection correspondence is modeled as a **notice**. A `CollectionsAgent` drafts one by supplying the `account_id` and the `notice_type`, one of `VALIDATION`, `DEMAND`, `INTENT_TO_LIEN`, or `INTENT_TO_FORECLOSE`. A notice opens in `DRAFT` with a null `sent_date` and a null `dispute_date`; its `status` ranges over `DRAFT`, `SENT`, `DISPUTED`, `EXPIRED`, and `VOID`. Notices are transitioned through a single action that names the target `to_status`.

**Sending.** Moving a `DRAFT` notice to `SENT` stamps its `sent_date` with the logical-clock now. A send is blocked, however, if a same-`notice_type` notice already sent on the account is still inside its cooldown window: the window runs from that prior notice's `sent_date` up to but not including `sent_date` plus 30 days (a half-open interval), and any prior notice in `SENT` or `DISPUTED` whose window contains now blocks the new send with `ERR_NOTICE_COOLDOWN`.

**Disputing and re-sending.** A consumer dispute moves a `SENT` notice to `DISPUTED`, stamping `dispute_date` with the logical-clock now; this is allowed only while the dispute falls inside the validation window — that is, while (now minus `sent_date`) is strictly less than 30 days — otherwise `ERR_INVALID_STATE`. While any notice on the account is `DISPUTED`, escalation to lien or foreclosure is paused (see §3.6). The agent responds by mailing verification, moving the notice from `DISPUTED` back to `SENT`; this resets `sent_date` to now (restarting the validation clock) and clears `dispute_date`. A notice may therefore cycle `SENT → DISPUTED → SENT` any number of times.

**Expiring and voiding.** A `SENT` notice may be moved to `EXPIRED` only once its validation period has fully run — (now minus `sent_date`) at least 30 days — else `ERR_INVALID_STATE`. A notice in `DRAFT` or `SENT` may be voided outright to `VOID`.

### 3.5. Payment Plans and Breach

When an owner agrees to pay over time, a `CollectionsAgent` drafts a **payment plan** against the account. The create carries the `account_id`, the `total_amount_cents` financed, the `installment_cents` due each month, the `num_installments` (at least 1), the `first_due_date`, and the OCC guard `expected_account_version` described in §2.6; `total_amount_cents` must be positive (`ERR_INVALID_AMOUNT`). The plan's `final_due_date` is computed as the `first_due_date` plus thirty days for each installment beyond the first — that is, plus (`num_installments` minus one) times 30 days — and defines the plan's occupied interval from `first_due_date` through `final_due_date`. A new plan may not be created if that interval strictly overlaps the interval of any non-terminal plan already on the account (a non-terminal plan is one whose `status` is not `COMPLETED` and not `CANCELLED`); such a collision yields `ERR_PLAN_OVERLAP`. Two intervals strictly overlap exactly when the new interval's `first_due_date` is strictly before the existing interval's `final_due_date` **and** the existing interval's `first_due_date` is strictly before the new interval's `final_due_date`. Consequently, two plans that merely touch at a single shared endpoint (one's `final_due_date` equal to the other's `first_due_date`) do not overlap and are both allowed, whereas a zero-length interval — a single-installment plan, whose `first_due_date` equals its `final_due_date` — that falls strictly inside an existing plan's interval does overlap and is rejected. A plan begins in `DRAFT`; its `status` ranges over `DRAFT`, `ACTIVE`, `BREACHED`, `SUSPENDED`, `COMPLETED`, and `CANCELLED`.

Activating a plan (`DRAFT → ACTIVE`, or reinstating `BREACHED → ACTIVE`) requires the account to be in `DELINQUENT` or `PAYMENT_PLAN`, else `ERR_INVALID_STATE`; activation moves a `DELINQUENT` account to `PAYMENT_PLAN`. Each plan exposes a computed `amount_paid_cents`, the cumulative payments credited to the plan's account since activation, and a computed `missed_count`.

**Breach evaluation.** The `missed_count` is derived at the logical-clock now from the installment schedule. The number of installments due is the count of installment ordinals whose scheduled date — the `first_due_date` plus thirty days for each ordinal beyond the first — is at or before now. The expected cumulative payment is that count of due installments (never exceeding `num_installments`) multiplied by `installment_cents`. If `amount_paid_cents` is at least the expected amount, `missed_count` is zero; otherwise it is the shortfall (expected minus paid) divided by `installment_cents` and rounded **up** to a whole installment. A plan may be moved `ACTIVE → BREACHED` only when `missed_count` is at least 2; a breach attempted below that threshold is refused with `ERR_PLAN_NOT_BREACHABLE`. Breaching returns the account from `PAYMENT_PLAN` to `DELINQUENT`. Reinstating a `BREACHED` plan to `ACTIVE` requires that the account has caught up — `missed_count` back below 2 — and moves the account to `PAYMENT_PLAN`.

A plan may be completed (`ACTIVE → COMPLETED`) only when `amount_paid_cents` has reached `total_amount_cents`, else `ERR_INVALID_STATE`. A `DRAFT` plan may be cancelled outright; cancelling an `ACTIVE` plan (`ACTIVE → CANCELLED`) returns the account from `PAYMENT_PLAN` to `DELINQUENT`.

### 3.6. Liens and Foreclosure Referral

Legal escalation is the province of the `ComplianceOfficer`. Recording a **lien** on an account (supplying the `account_id`) is gated by a sequence of compliance checks evaluated in the order of §2.7. The account must not be under a bankruptcy stay (`ERR_AUTOMATIC_STAY`) and must have no `DISPUTED` notice (`ERR_ACTIVE_DISPUTE`). A qualifying predecessor must exist: at least one notice of type `INTENT_TO_LIEN` on the account must be in `SENT`; absent that, the recording is refused with `ERR_DEMAND_NOTICE_REQUIRED`. This predecessor test is applied *before* the temporal test. Given a sent intent-to-lien notice, the FDCPA validation period must have fully elapsed — (now minus that notice's `sent_date`) at least 30 days — else `ERR_VALIDATION_PERIOD_ACTIVE`. Finally, the account's `total_balance_cents` must be at least the lien minimum of 180,000 cents (one thousand eight hundred dollars); below it, recording is refused with `ERR_LIEN_MINIMUM_NOT_MET`.

A recorded lien captures `recorded_amount_cents` as a snapshot of the account's `total_balance_cents` at the recording instant, stamps `recorded_date` with the logical-clock now, and records the acting officer's `X-User-ID` as `recorded_by_user_id`. The lien opens in `RECORDED` — its `status` ranges over `RECORDED`, `STAYED`, `FORECLOSING`, and `RELEASED` — and moves the account from `DELINQUENT` to `LIEN`. A `ComplianceOfficer` may manually release a `RECORDED` lien to `RELEASED`.

A **foreclosure referral** hands a recorded lien to counsel. The `ComplianceOfficer` creates it with the `account_id`, the `lien_id` of the lien being foreclosed, and the `attorney_name`, the acting `X-User-ID` is stored as `referred_by_user_id`, and the `referred_date` is stamped with the logical-clock now. A **maker-checker separation of duties** applies: the officer creating the referral must differ from the officer who recorded the referenced lien — if `referred_by_user_id` would equal that lien's `recorded_by_user_id`, the referral is refused with `ERR_SEGREGATION_OF_DUTIES`. Referral also requires that a `RECORDED` lien exist on the account (`ERR_LIEN_REQUIRED`) and, like lien recording, is blocked by an active bankruptcy stay (`ERR_AUTOMATIC_STAY`) or a `DISPUTED` notice (`ERR_ACTIVE_DISPUTE`). A referral opens in `REFERRED`; its `status` ranges over `REFERRED`, `FILED`, `STAYED`, `SALE_COMPLETED`, and `WITHDRAWN`.

Advancing a referral from `REFERRED` to `FILED` requires the referenced lien to still be `RECORDED` (`ERR_INVALID_STATE`) and the account not to be in `BANKRUPTCY` (`ERR_AUTOMATIC_STAY`); filing moves the account from `LIEN` to `FORECLOSURE` and moves the referenced lien from `RECORDED` to `FORECLOSING`. Completing a sale (`FILED → SALE_COMPLETED`), again barred under bankruptcy (`ERR_AUTOMATIC_STAY`), moves the account from `FORECLOSURE` to `CHARGED_OFF` — which itself waives every `OPEN` or `PARTIAL` assessment on the account — and releases the referenced lien from `FORECLOSING` to `RELEASED`. A referral may instead be **withdrawn**: withdrawing a `REFERRED` referral releases its `FORECLOSING` lien if applicable, while withdrawing a `FILED` referral returns the account from `FORECLOSURE` to `DELINQUENT` and returns the referenced lien from `FORECLOSING` to `RECORDED`.

Finally, when a payment clears an account under lien and drives `total_balance_cents` to zero, the `RECORDED` lien is released and the account returns to `CURRENT`, as noted in §3.1.

### 3.7. Bankruptcy and the Automatic Stay

A bankruptcy petition freezes collection. A `ComplianceOfficer` records a **bankruptcy case** against an account with the `account_id`, the `chapter` (`CH7` or `CH13`), the court `case_number`, and the `filed_date` (the petition date that imposes the stay). The case opens in `FILED` — its `status` ranges over `FILED`, `DISCHARGED`, and `DISMISSED` — and moves the account into `BANKRUPTCY` from whatever collection stage it occupied.

Recording the case triggers the automatic-stay **cascade**, applied atomically: every `RECORDED` lien on the account moves to `STAYED`, and every `FORECLOSING` lien likewise moves to `STAYED`; every `FILED` or `REFERRED` foreclosure referral moves to `STAYED`; and any `ACTIVE` payment plan moves to `SUSPENDED`. While the account is in `BANKRUPTCY`, no lien recording, foreclosure referral or advance, or notice send is permitted — each is refused with `ERR_AUTOMATIC_STAY`.

Resolution takes one of two forms. **Dismissal** (`FILED → DISMISSED`) lifts the stay and restores the pre-petition posture: the account returns from `BANKRUPTCY` to `DELINQUENT`, every `STAYED` lien returns to `RECORDED`, every `STAYED` referral returns to `REFERRED`, and any `SUSPENDED` plan returns to `ACTIVE`. **Discharge** (`FILED → DISCHARGED`) finalizes the write-off: the account moves from `BANKRUPTCY` to `CHARGED_OFF`, every `OPEN` or `PARTIAL` assessment is waived, and every `STAYED` or `RECORDED` lien is released to `RELEASED`.

### 3.8. Payoff Quotes

Any of a `CollectionsAgent`, `ComplianceOfficer`, or the account's own `AssociationManager` may request a **payoff quote** for an account. The quote comes in two variants selected by `variant`: `PROVISIONAL` (the default) accrues interest through today, while `BINDING` projects interest forward through the good-through date, which is the logical-clock now plus 15 days. The quote's `quote_date` is the logical-clock now, and its `good_through_date` is now for a provisional quote or now-plus-15-days for a binding one.

Interest accrues only on **principal** — assessments in `OPEN` or `PARTIAL` whose `charge_type` is `REGULAR` or `SPECIAL`; late fees, prior interest, attorney costs, and fines are excluded from the interest base (though they remain part of the account's `total_balance_cents`). For each such principal assessment, the day count is the floor of (the projection instant minus the assessment's `due_date`) in whole days, taken as zero if that difference is negative. The raw interest is the assessment's `balance_cents` multiplied by the association's `interest_rate_annual_pct` divided by 100, multiplied by the day count divided by a 365-day year. That raw value is rounded half-up to whole cents per assessment, then capped so it never exceeds that assessment's `balance_cents` (a per-assessment usury cap), and the capped per-assessment amounts are summed into `accrued_interest_cents`. The `payoff_amount_cents` is the account's `total_balance_cents` plus `accrued_interest_cents`. The response echoes the `account_id`, the `variant`, the `quote_date`, the `good_through_date`, the `total_balance_cents`, the `accrued_interest_cents`, and the `payoff_amount_cents`.

### 3.9. Trust Accounting and Remittances

Collected funds are held in trust for each association and periodically remitted, net of the management fee. A `TrustAccountant` drafts a **remittance** by supplying the `association_id`, the inclusive `period_start` and `period_end` of the collection period, an optional `basis`, and the OCC guard `expected_association_version` of §2.6. The period end must not be earlier than the period start, else `ERR_PERIOD_INVALID`. A remittance opens in `PENDING`; its `status` ranges over `PENDING`, `REMITTED`, and `VOID`.

**Included payments.** The candidate pool is every payment on the association's accounts whose `received_date` falls within the period, inclusive of both `period_start` and `period_end`. The `basis` (default `CASH`) selects a dual-variant computation. Under `CASH`, the pool includes every payment that was ever posted in the window, even one later reversed — a cash estimate. Under `NET`, only payments still in `POSTED` at compute time are included, excluding any currently reversed, which yields a lower gross whenever a period payment was reversed.

**Amounts.** The `gross_amount_cents` is the sum of `amount_cents` across the included payments. The `management_fee_cents` is computed per payment — each included payment's `amount_cents` multiplied by the association's `management_fee_pct` divided by 100, rounded half-up to whole cents — and then summed across payments. The `net_amount_cents` is `gross_amount_cents` minus `management_fee_cents`.

**Execution.** A `TrustAccountant` executes a `PENDING` remittance by moving it to `REMITTED`, but only when the association's `trust_balance_cents` is at least the remittance's `gross_amount_cents`; an out-of-trust remittance is refused with `ERR_INVALID_AMOUNT`. Executing decreases the association's `trust_balance_cents` by `gross_amount_cents`. A `PENDING` remittance may instead be voided to `VOID` with no cash effect. Remittances may be listed and filtered by their `association_id`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/collections` prefix. Creating a new resource returns HTTP 201; reads, list operations, transitions, and other modifications return HTTP 200. Request and response payloads are not restated here — reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/collections/_clock/set_current_utc` | Set the server logical clock | CollectionsAgent, ComplianceOfficer, TrustAccountant |
| POST | `/collections/associations` | Onboard a community association | CollectionsAgent |
| GET | `/collections/associations/{associationId}` | Read an association (includes trust balance) | CollectionsAgent, ComplianceOfficer, TrustAccountant, AssociationManager |
| GET | `/collections/associations/{associationId}/aging-report` | Association-wide delinquency/aging summary | CollectionsAgent, ComplianceOfficer, TrustAccountant, AssociationManager |
| POST | `/collections/accounts` | Create a delinquent-collections account | CollectionsAgent |
| GET | `/collections/accounts/{accountId}` | Read an account (includes balance and aging) | CollectionsAgent, ComplianceOfficer, TrustAccountant, AssociationManager |
| GET | `/collections/accounts` | List accounts, optionally filtered | CollectionsAgent, ComplianceOfficer, TrustAccountant, AssociationManager |
| POST | `/collections/accounts/{accountId}/transition` | Manual account transition (DELINQUENT, CLOSED) | CollectionsAgent, ComplianceOfficer |
| POST | `/collections/assessments` | Post a charge to an account | CollectionsAgent |
| GET | `/collections/assessments/{assessmentId}` | Read an assessment | CollectionsAgent, ComplianceOfficer, TrustAccountant, AssociationManager |
| GET | `/collections/assessments` | List assessments filtered by account | CollectionsAgent, ComplianceOfficer, TrustAccountant, AssociationManager |
| POST | `/collections/assessments/{assessmentId}/waive` | Waive an OPEN/PARTIAL assessment | CollectionsAgent |
| POST | `/collections/payments` | Record a payment; run the allocation waterfall | CollectionsAgent |
| GET | `/collections/payments/{paymentId}` | Read a payment (includes allocations) | CollectionsAgent, ComplianceOfficer, TrustAccountant, AssociationManager |
| GET | `/collections/payments` | List payments filtered by account | CollectionsAgent, ComplianceOfficer, TrustAccountant, AssociationManager |
| POST | `/collections/payments/{paymentId}/reverse` | Reverse a POSTED payment | CollectionsAgent |
| POST | `/collections/notices` | Draft an FDCPA notice/demand | CollectionsAgent |
| GET | `/collections/notices/{noticeId}` | Read a notice | CollectionsAgent, ComplianceOfficer, TrustAccountant, AssociationManager |
| GET | `/collections/notices` | List notices filtered by account | CollectionsAgent, ComplianceOfficer, TrustAccountant, AssociationManager |
| POST | `/collections/notices/{noticeId}/transition` | Transition a notice per its state machine | CollectionsAgent |
| POST | `/collections/payment-plans` | Create a payment-plan agreement (OCC-guarded) | CollectionsAgent |
| GET | `/collections/payment-plans/{planId}` | Read a payment plan | CollectionsAgent, ComplianceOfficer, TrustAccountant, AssociationManager |
| GET | `/collections/payment-plans` | List payment plans filtered by account | CollectionsAgent, ComplianceOfficer, TrustAccountant, AssociationManager |
| POST | `/collections/payment-plans/{planId}/transition` | Transition a payment plan per its state machine | CollectionsAgent |
| POST | `/collections/liens` | Record a lien on an account | ComplianceOfficer |
| GET | `/collections/liens/{lienId}` | Read a lien | CollectionsAgent, ComplianceOfficer, TrustAccountant, AssociationManager |
| GET | `/collections/liens` | List liens filtered by account | CollectionsAgent, ComplianceOfficer, TrustAccountant, AssociationManager |
| POST | `/collections/liens/{lienId}/transition` | Manually release a RECORDED lien | ComplianceOfficer |
| POST | `/collections/foreclosure-referrals` | Refer an account to foreclosure counsel | ComplianceOfficer |
| GET | `/collections/foreclosure-referrals/{referralId}` | Read a foreclosure referral | CollectionsAgent, ComplianceOfficer, TrustAccountant, AssociationManager |
| GET | `/collections/foreclosure-referrals` | List referrals filtered by account and/or lien | CollectionsAgent, ComplianceOfficer, TrustAccountant, AssociationManager |
| POST | `/collections/foreclosure-referrals/{referralId}/transition` | Advance a referral per its state machine | ComplianceOfficer |
| POST | `/collections/bankruptcy-cases` | Record a bankruptcy filing (imposes the stay) | ComplianceOfficer |
| GET | `/collections/bankruptcy-cases/{caseId}` | Read a bankruptcy case | CollectionsAgent, ComplianceOfficer, TrustAccountant, AssociationManager |
| GET | `/collections/bankruptcy-cases` | List bankruptcy cases filtered by account | CollectionsAgent, ComplianceOfficer, TrustAccountant, AssociationManager |
| POST | `/collections/bankruptcy-cases/{caseId}/transition` | Discharge or dismiss a bankruptcy case | ComplianceOfficer |
| POST | `/collections/remittances` | Draft a trust remittance (OCC-guarded) | TrustAccountant |
| GET | `/collections/remittances/{remittanceId}` | Read a remittance | TrustAccountant, ComplianceOfficer, AssociationManager |
| GET | `/collections/remittances` | List remittances filtered by association | TrustAccountant, ComplianceOfficer, AssociationManager |
| POST | `/collections/remittances/{remittanceId}/transition` | Remit or void a PENDING remittance | TrustAccountant |
| GET | `/collections/accounts/{accountId}/payoff-quote` | Compute a payoff statement (PROVISIONAL/BINDING) | CollectionsAgent, ComplianceOfficer, AssociationManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_AUTOMATIC_STAY` | 403 |
| `ERR_ACTIVE_DISPUTE` | 409 |
| `ERR_VALIDATION_PERIOD_ACTIVE` | 409 |
| `ERR_NOTICE_COOLDOWN` | 409 |
| `ERR_DEMAND_NOTICE_REQUIRED` | 409 |
| `ERR_LIEN_REQUIRED` | 409 |
| `ERR_LIEN_MINIMUM_NOT_MET` | 422 |
| `ERR_PLAN_OVERLAP` | 409 |
| `ERR_PLAN_NOT_BREACHABLE` | 409 |
| `ERR_NOT_DELINQUENT` | 409 |
| `ERR_INVALID_AMOUNT` | 422 |
| `ERR_PERIOD_INVALID` | 422 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_VALIDATION` | 422 |
