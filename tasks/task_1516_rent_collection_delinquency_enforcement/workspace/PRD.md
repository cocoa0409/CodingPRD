# Rent Collection & Delinquency Enforcement API — Product Requirements Document

## 1. Introduction

For a residential property management company, the rent ledger is the operational system of record: every fee assessed, every dollar tendered across every payment channel, every waiver granted, and every statutory notice served must reconcile to the cent and survive audit. Collection practice is further governed by jurisdictional rules — caps on late fees and returned-payment fees, cure windows on pay-or-quit notices, acceptance rules for partial payments, and minimum balances for collections referral — that vary by state and must be enforced mechanically rather than by operator memory. This document specifies the Rent Collection & Delinquency Enforcement API, which manages that lifecycle end to end: property policy configuration, lease and ledger administration, payment posting under a configurable posting priority, late-fee assessment under grace periods and statutory caps, pay-or-quit notice generation and service documentation, payment plan origination and default, returned-payment and NSF handling, ledger dispute resolution, and post-move-out collections referral.

Four operator populations use the API under strictly segregated duties. Front-office staff record payments and draft enforcement artifacts; property managers alone activate and end leases, grant waivers, issue and serve notices, approve payment plans, resolve disputes, and refer balances to collections; tenants act only on their own ledger; and an operations identity drives the scheduled delinquency sweep and the logical clock that every date rule reads. Because several workflows mutate more than one aggregate at a time — a returned check ripples through allocations, charges, notices, and referrals — this specification is explicit about cascade ordering, recomputation rules, and the optimistic-concurrency guards that keep a writer holding a stale view of a lease from silently superseding work it never saw.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope formats, and cross-cutting principles that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. Exactly four roles are recognized, spelled precisely as follows: `PropertyManager`, `LeasingAgent`, `Tenant`, and `SystemOps`. A request missing either header, or presenting a role outside this set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not permitted on the target endpoint — including action-level restrictions such as dispute resolution being `PropertyManager`-only and dispute reopening being `Tenant`-only, and ownership checks requiring a `Tenant` to act only on their own lease graph — is rejected with `ERR_UNAUTHORIZED`.

The meaning of `X-User-ID` depends on the role presented. When `X-User-Role` is `Tenant`, `X-User-ID` is the `id` of the acting `Tenant` record; ownership checks on any resource that references a tenant compare the resource's tenant-referencing foreign key — a lease's `primary_tenant_id`, a payment's `tenant_id`, a dispute's `tenant_id` — to `X-User-ID`. When `X-User-Role` is `PropertyManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `approved_by_user_id` on a payment plan or `served_by_user_id` on a notice — but does not compare it to any entity's `id`. When `X-User-Role` is `LeasingAgent`, `X-User-ID` is likewise an opaque operator identifier, recorded where the workflow calls for it (for example as `created_by_user_id` on a manually created charge or `drafted_by_user_id` on a drafted payment plan) but never compared to an entity's `id`. When `X-User-Role` is `SystemOps`, `X-User-ID` is again an opaque operator identifier; it names the automation identity behind the delinquency sweep and the logical clock and carries no business-mutation rights beyond those two capabilities, though it may perform all read operations.

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

---

### 2.3. Pagination

Endpoints that return lists of resources accept two query parameters. The `limit` parameter specifies the maximum number of items to return; when not provided it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order.

List responses carry the following pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Money, Calendar Dates, and the Logical Clock

All monetary values in the system — charge amounts, fees, statutory caps, outstanding balances, waived totals, and allocation amounts — are represented as integer cents. Arithmetic on monetary values is exact except where a calculation explicitly nominates rounding; in those cases (the percentage component of a daily late fee and the proration of a straddling rent charge) the value is rounded half up to whole cents. Calendar dates are exchanged as strings in `YYYY-MM-DD` form, while datetimes are ISO 8601 UTC timestamps with three fractional digits.

Every date-dependent rule in this document — grace periods, cure deadlines, cooling-off windows, received-date ceilings, and every comparison against "today" — reads a server-side logical clock, never the wall clock. The logical clock starts at exactly 2026-08-01T00:00:00Z before any clock-setting call is made, and it never falls back to wall-clock time thereafter. A `SystemOps`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and reports the resulting `current_utc`.

### 2.5. Common Resource Properties

All primary resources in the system — properties, tenants, leases, ledger charges, payments, delinquency notices, payment plans, disputes, and collections referrals — carry a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- **`version` (integer):** a system-managed integer that increments by exactly one on every mutation of the resource, whether the mutation came from a client request or from an automatic system transition.

The payment allocation is the sole exception to this convention. As an append-only ledger entry it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Property-Governed Policy Constants

Each property record carries the statutory and policy constants that govern every lease under it: the posting priority policy, the late-fee cap, the returned-payment (NSF) fee cap, the monthly waiver cap, the minimum partial-payment percentage, the collections referral threshold, the notice cure period, the plan cooling-off window, and the plan setup fee together with its balance threshold. A lease never copies these values; every rule that needs a cap or threshold reads it from the property that owns the lease at the moment the rule is evaluated. The individual constants are introduced with the workflows that consume them in §3.

### 2.7. Ledger Integrity and Cross-Entity Cascades

The ledger is kept consistent by three named cascade chains, each of which is described in full with its triggering workflow in §3 and summarized here. **Cascade A** fires when a posted payment is returned by the bank: the payment flips to its returned state, every allocation it created is reversed by an equal and opposite allocation, each affected charge recomputes its balance and reopens as warranted, every draft notice covering an affected charge recomputes its demanded amount, a returned-payment fee charge is created, and any pending collections referral on the lease recomputes its balance — with a referral being created on the spot when an ended lease's balance is pushed back above zero. **Cascade B** fires when a lease ends at move-out: draft notices and non-terminal plans on the lease are cancelled, and a reconciliation balance is computed that, when positive, produces a pending collections referral. **Cascade C** fires when a dispute is resolved with an adjustment: the charge's face amount is corrected, its outstanding balance is recomputed, covering draft notices and the pending referral recompute in turn, and a referral whose recomputed balance has fallen below the referral threshold is recalled automatically.

Two integrity principles apply universally. First, every mutation described anywhere in this document — client-driven transitions and automatic system transitions alike — refreshes the affected resource's `updated_at` and increments its `version` by exactly one; this includes cascaded mutations on notices, plans, charges, payments, referrals, and the lease whose draft artifacts are superseded. Second, the server transitions resources automatically when cascade or sweep criteria are met, without requiring a client request addressed to the affected resource.

### 2.8. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control: drafting a delinquency notice and drafting a payment plan. Each of these creation requests must carry `expected_lease_version`, a non-optional field holding the `version` of the target lease as the client last observed it. If the lease's current `version` no longer matches — because another writer has advanced it since the client last read the lease — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412). The guard exists because both creations are create-with-supersede operations: each cancels an existing draft sibling on the lease as a side effect, so a writer holding a stale lease version would otherwise cancel a draft it never observed. Endpoints not named here do not accept a version field at all.

### 2.9. Validation Order: First Failure Wins

Every request is evaluated against an ordered validation pipeline. The first failing check produces the error response; later checks are not evaluated. The order is:

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers are present and the role is one of the declared roles; otherwise `ERR_UNAUTHENTICATED`.
2. **Authorization.** The role is permitted on the endpoint and on the requested action, including ownership checks (a `Tenant` must act on their own lease, payments, and disputes); otherwise `ERR_UNAUTHORIZED`.
3. **Path existence.** Identifiers appearing in the URL path are validated for existence in left-to-right order — the lease first, then the charge, payment, notice, plan, dispute, or referral beneath it; the first missing identifier yields `ERR_NOT_FOUND`.
4. **Body reference existence.** Foreign keys supplied in the request body — `property_id`, `primary_tenant_id`, `lease_id`, `tenant_id`, and every element of `charge_ids` — must reference existing resources; otherwise `ERR_NOT_FOUND`.
5. **Optimistic concurrency.** Where §2.8 applies, `expected_lease_version` must equal the lease's current `version`; otherwise `ERR_STALE_VERSION`.
6. **Lease lifecycle gate.** Operations that require an `ACTIVE` lease (payment posting, notice creation and issuance, plan creation) fail with `ERR_LEASE_NOT_ACTIVE` while the lease is still in `DRAFT`; operations that are never permitted once a lease has ended (charge creation, payment creation, payment posting, notice creation and issuance, plan creation) fail with `ERR_LEASE_ALREADY_ENDED` on an `ENDED` lease.
7. **Resource transition preconditions.** Each resource's transition is checked against its state machine — a payment must be `PENDING` or `RETURNED` to post and `POSTED` to return (`ERR_PAYMENT_INVALID_TRANSITION`); a notice must be `DRAFT` to issue and `ISSUED` to serve (`ERR_NOTICE_INVALID_TRANSITION`); a plan must be `DRAFT` to approve (`ERR_PLAN_INVALID_TRANSITION`); a dispute must be `OPEN` or `REOPENED` to resolve and `RESOLVED_UPHELD` to reopen (`ERR_DISPUTE_INVALID_TRANSITION`, or `ERR_DISPUTE_REOPEN_EXHAUSTED` when the single reopen has already been spent); a referral transition must be permitted from its current status (`ERR_REFERRAL_INVALID_TRANSITION`); a waiver target charge must be `OPEN` or `PARTIALLY_PAID` (`ERR_CHARGE_NOT_WAIVABLE`).
8. **Segregation of duties.** The plan approver must differ from the plan's drafter, and the waiver caller must differ from the charge's creator; otherwise `ERR_SEGREGATION_OF_DUTIES`.
9. **Charge-to-lease referential integrity.** Every element of `charge_ids` must belong to the lease the request targets, and a dispute's charge must belong to the dispute's lease; otherwise `ERR_CHARGE_NOT_ON_LEASE`.
10. **Date coherence.** `term_start_date` must be strictly before `term_end_date`; `period_end_date` must be on or after `period_start_date`; `received_date` must not be in the future; `move_out_date` must lie within the lease term's start date and today; `served_date` must lie within the issued date and the cure deadline; `first_installment_date` must be strictly after today. Violations yield `ERR_INVALID_REQUEST`.
11. **Notice service window.** At service-recording time, `served_date` outside the window from `issued_date` through `cure_deadline_date` yields the dedicated `ERR_NOTICE_SERVICE_WINDOW`.
12. **Plan schedule.** At plan-creation time, a `first_installment_date` that is not strictly after today, or an `installment_count` outside the permitted range, yields the dedicated `ERR_INVALID_INSTALLMENT_SCHEDULE`.
13. **Uniqueness and overlap constraints.** Half-open lease terms must not overlap on the same unit (`ERR_LEASE_TERM_OVERLAP`); notice coverage windows must not overlap across issued or served notices of a lease (`ERR_NOTICE_PERIOD_OVERLAP`); at most one `ACTIVE` plan may exist per lease (`ERR_PLAN_EXISTS`); the plan cooling-off window must have elapsed (`ERR_PLAN_COOLING_OFF`); a manually created charge's kind must be `RENT` or `DAMAGE_FEE` (`ERR_INVALID_REQUEST`); a returnable payment's channel must be `ACH` or `CHECK` (`ERR_CHANNEL_NOT_RETURNABLE`).
14. **Cross-entity gates.** A plan may not be approved while any notice on the lease is `SERVED` (`ERR_ACTIVE_NOTICE_BLOCKS_PLAN`); a referral may not proceed while any dispute on the lease is `OPEN` or `REOPENED` (`ERR_BLOCKING_DISPUTE`).
15. **Payment acceptance.** The payment amount must not exceed the lease's total outstanding (`ERR_OVERPAYMENT_REJECTED`), and a partial amount must clear the property's minimum partial-payment threshold unless it equals the total outstanding exactly (`ERR_PARTIAL_BELOW_MINIMUM`). The overpayment check is evaluated before the partial-minimum check.
16. **Waiver fiscal limits.** The waived amount must not exceed the charge's outstanding balance (`ERR_WAIVER_EXCEEDS_OUTSTANDING`), and the property's calendar-month waiver total must remain within its cap (`ERR_WAIVER_CAP_EXCEEDED`), evaluated in that order.
17. **Referral fiscal threshold.** The referral balance must meet the property's collections threshold; otherwise `ERR_REFERRAL_THRESHOLD_NOT_MET`.
18. **Request shape.** Required fields are present, enum values are valid, identifiers are well-formed, no undeclared fields appear in the payload, and an adjusted amount accompanies an adjusted dispute outcome within its permitted range; otherwise `ERR_INVALID_REQUEST`.

### 2.10. Nested Resource Retrieval

Requests that target nested resources — for example a charge listed under a lease, or a notice collection beneath a lease identifier — are validated strictly left to right along the path. The server confirms the parent identifier exists before examining the child, and the request is rejected immediately with `ERR_NOT_FOUND` naming the first identifier that does not correspond to an existing resource. The same discipline applies to the reverse-reachability listings that expose each child collection under its lease: the lease is resolved first, and only then are filters applied to its charges, notices, plans, or referrals.


## 3. Business Logic & Workflows

### 3.1. Portfolio Setup: Properties, Tenants, and Leases

Everything begins with the property. A `PropertyManager` registers a property by supplying its display `name` and a two-letter `state_code` identifying the jurisdiction whose statutory caps apply. The same payload fixes the property's policy constants for the life of every lease beneath it: `posting_priority_policy`, which selects the payment-posting waterfall order and takes one of two values — `FEES_FIRST`, under which late fees, returned-payment fees, plan setup fees, and damage fees are satisfied before rent, or `RENT_FIRST`, under which rent is satisfied first; `late_fee_cap_cents`, the statutory ceiling on a single period's late fee; `nsf_fee_cap_cents`, the ceiling on a single returned-payment fee; `monthly_waiver_cap_cents`, the maximum total cents that may be waived across the property in one calendar month; `min_partial_payment_percent`, an integer percentage from 1 to 100 defining the smallest acceptable partial payment; `collections_threshold_cents`, the minimum move-out balance that may be sent to collections; `notice_cure_period_days`, the cure window granted by a pay-or-quit notice; `plan_cooling_off_days`, the waiting period after a defaulted plan during which no new plan may be drafted on that lease; `plan_setup_fee_cents`, the flat origination fee for a payment plan; and `plan_setup_fee_threshold_cents`, the covered balance at or above which that fee is charged.

Tenant registration is a front-office task shared by `LeasingAgent` and `PropertyManager`. A tenant record carries the tenant's `full_name`, a contact `email` that must be unique per tenant, and an optional `phone` that defaults to an empty string when omitted.

With a property and a tenant in place, either a `LeasingAgent` or a `PropertyManager` creates a lease. The lease names its owning `property_id` and its `primary_tenant_id` — the tenant responsible for the ledger — along with a `unit_label` identifying the physical unit; the pair of property and unit label is the occupancy resource on which term-overlap checks run. Financial and temporal terms are set at creation: `monthly_rent_cents`, the full-period rent used by proration and by percentage-based fee math; `due_day`, the day of month rent falls due, an integer from 1 to 28; `grace_period_days`, the days after the due date before a late fee accrues; and the late-fee formula selector `late_fee_type`, one of `FLAT` or `PERCENT_PLUS_DAILY`, with its parameters `late_fee_flat_cents`, `late_fee_percent_bps`, and `late_fee_daily_cents`, each defaulting to 0 when omitted. The lease term runs from `term_start_date` to `term_end_date` as a half-open interval — the start date counts as occupied, the end date does not — and the start must be strictly before the end. A new lease begins life in `DRAFT` status.

Activation is a `PropertyManager` act. Lifecycle changes throughout the system are requested through a transition payload whose `action` field names the requested move; for a lease the actions are `ACTIVATE` and `MOVE_OUT`, the latter carrying the `move_out_date` described in §3.9. Activating a lease — moving it from `DRAFT` to `ACTIVE` — is permitted only when its `term_end_date` is still in the future and no other `ACTIVE` lease on the same property and unit label has a term that intersects it; because terms are half-open, two leases whose terms merely touch, one ending on the day the next begins, do not conflict, while a genuine intersection is rejected with `ERR_LEASE_TERM_OVERLAP`. Requesting activation on a lease that is no longer in `DRAFT` is rejected with `ERR_INVALID_REQUEST`. Any of the four roles may read a lease or list leases; the listing accepts `property_id`, `primary_tenant_id`, and `status` as filters, with `limit` and `offset` for pagination.

### 3.2. The Lease Ledger: Charges and Balance Reads

Every financial obligation lives on the lease ledger as a charge. A `LeasingAgent` or `PropertyManager` creates a charge manually by supplying its `kind`, the coverage window `period_start_date` and `period_end_date` (the end must fall on or after the start), the `due_date` that drives both grace-and-late-fee math and waterfall ordering, and the face `amount_cents`. Manual creation is restricted to the `RENT` and `DAMAGE_FEE` kinds — a payload naming any other kind is rejected with `ERR_INVALID_REQUEST` — and is allowed while the lease is `DRAFT` or `ACTIVE`; once the lease has ended, charge creation is rejected with `ERR_LEASE_ALREADY_ENDED`. The remaining kinds arise only from system pathways: a `LATE_FEE` is created by the delinquency sweep, an `NSF_FEE` by a payment return, and a `PLAN_SETUP_FEE` by plan origination. Each charge records a `source` — `MANUAL` by default, or `SWEEP`, `PLAN`, or `RETURN` for system-created charges — and a `created_by_user_id` holding the creator's `X-User-ID`, or the literal string `system` for charges born of the sweep, a return, or a plan. For a system charge, the coverage period is inherited from its origin: a late fee carries the rent charge's period, and a returned-payment fee is stamped with the return date as both its period and its due date.

A charge opens in `OPEN` status with `waived_cents` at 0. Its `outstanding_cents` is a computed figure — the face amount, minus waived cents, minus the net applied cents (the sum of `APPLY` allocations minus the sum of `REVERSE` allocations) — recomputed on every allocation, waiver, reversal, or dispute adjustment. The face `amount_cents` itself is reduced in place only by an adjusted dispute resolution. From `OPEN`, a charge moves to `PARTIALLY_PAID` when an allocation covers less than the outstanding balance; from either `OPEN` or `PARTIALLY_PAID`, it moves to `PAID` when net applied cents exactly cover the face amount net of waivers. A returned payment walks these states backward: a reversal that restores part of a paid charge's balance moves it from `PAID` back to `PARTIALLY_PAID`; reversals that cancel every application restore it from `PAID` to `OPEN`, and likewise a partially paid charge whose net applied cents fall to zero returns from `PARTIALLY_PAID` to `OPEN`. Two further terminal states exist: `WAIVED`, reachable only through the waiver action, and `VOID`, reached when a dispute adjustment reduces the amount to zero. A charge that is already `PAID`, `WAIVED`, or `VOID` accepts no waiver.

For reconciliation, a computed ledger read of a lease — available to `PropertyManager` and `LeasingAgent` — reports two balance variants plus the identity components behind them: `forward_balance_cents`, the simple sum of outstanding balances over the lease's `OPEN` and `PARTIALLY_PAID` charges, counting every open charge at face value including charges whose due dates lie after any move-out (the acceleration view); `chronological_balance_cents`, the move-out-aware variant whose proration rules are defined with the move-out workflow in §3.9; and the components `total_charged_cents`, `total_waived_cents`, `total_applied_net_cents`, `total_outstanding_cents`, and `open_charge_count`. A lease's charge collection may be listed with `status` and `kind` filters, and a single charge may be read by any role; a `Tenant` reader sees only the ledger of their own lease.

### 3.3. Recording Payments and the Posting Waterfall

A payment enters the system in `PENDING` status, recorded against a lease by a `LeasingAgent` at the counter or by the `Tenant` themselves. The recording payload carries the `lease_id`, the paying `tenant_id`, the tender `channel` — one of `ACH`, `CARD`, `CHECK`, `MONEY_ORDER`, or `CASH` — and the tendered `amount_cents`. The `received_date` is optional and defaults to the server's current date; when supplied it must not lie in the future. A `Tenant` caller must supply their own tenant identifier, and it must equal the lease's `primary_tenant_id`; any other pairing is rejected with `ERR_UNAUTHORIZED`. Payment recording is refused outright once the lease has ended (`ERR_LEASE_ALREADY_ENDED`); a lease still in `DRAFT` may record a payment, but that payment cannot be posted until the lease is active. On a freshly recorded payment, `posted_date`, `return_reason_code`, and `nsf_fee_cents` are null and `return_count` is zero; each is set only by the lifecycle events that produce them.

Posting is requested through the payment's transition payload with the posting action, and is performed by a `LeasingAgent` or `PropertyManager`, and it is guarded by two acceptance rules evaluated against the lease's current outstanding — the sum of outstanding balances across the lease's `OPEN` and `PARTIALLY_PAID` charges. First, the tendered amount must not exceed that total; an overpayment is rejected with `ERR_OVERPAYMENT_REJECTED`. Second, a payment that does not exactly equal the total outstanding must be at least the total outstanding multiplied by the property's `min_partial_payment_percent`, divided by one hundred, and rounded up to a whole cent; anything smaller is rejected with `ERR_PARTIAL_BELOW_MINIMUM`. A payment equal to the full total outstanding is always accepted regardless of the percentage floor. Posting against a lease that is not `ACTIVE` fails — with `ERR_LEASE_NOT_ACTIVE` while the lease is in `DRAFT`, and with `ERR_LEASE_ALREADY_ENDED` once it has ended — and requesting the posting transition on a payment that is neither `PENDING` nor `RETURNED` fails with `ERR_PAYMENT_INVALID_TRANSITION`.

An accepted posting runs the payment waterfall. Eligible targets are the lease's charges in `OPEN` or `PARTIALLY_PAID` status with a positive outstanding balance. The property's `posting_priority_policy` fixes the class order: under `FEES_FIRST`, every charge of kind `LATE_FEE`, `NSF_FEE`, `PLAN_SETUP_FEE`, and `DAMAGE_FEE` is paid to zero before any cent reaches a `RENT` charge; under `RENT_FIRST`, rent charges are paid first and the fee classes follow. The two variants are not cosmetic — an identical payment posted against an identical ledger produces a different per-charge split under the two policies. Within a class, charges are ordered by `due_date` ascending, then by `created_at` ascending as the tie-break; identifiers are never consulted for ordering. The waterfall walks that order, allocating to each charge the lesser of the remaining payment money and that charge's outstanding balance, and stops the moment no payment money remains. Each allocation persists as an append-only payment allocation record carrying the `payment_id`, the `charge_id`, a `direction` of `APPLY`, the positive `amount_cents` moved (signed semantics come entirely from the direction), a one-based `allocation_order` reflecting the allocation's position within that posting run, and a free-text audit `note` that defaults to empty. Every touched charge then recomputes its `outstanding_cents` and flips status per §3.2, and the payment records the current date as its `posted_date`. A single posting may be replayed by reading one allocation, or the allocation collection may be listed with `payment_id` and `charge_id` filters; payments themselves may be listed with `lease_id`, `tenant_id`, and `status` filters, and a single payment read returns its full record.

### 3.4. Returned Payments, NSF Handling, and Re-presentment

Only bank-mediated tenders can come back: a return may be recorded on a `POSTED` payment whose `channel` is `ACH` or `CHECK`, while a return attempted on any other channel is rejected with `ERR_CHANNEL_NOT_RETURNABLE`. Because a bank return can arrive after a resident has moved out, the lease may be either `ACTIVE` or `ENDED` at return time; attempting the return on a payment that is not currently `POSTED` is rejected with `ERR_PAYMENT_INVALID_TRANSITION`. The `LeasingAgent` or `PropertyManager` recording the return supplies a `reason_code`, which is preserved on the payment as its `return_reason_code`, and may request a returned-payment fee via `nsf_fee_cents`.

The return fires Cascade A, in a fixed order. First, the payment itself flips from `POSTED` to `RETURNED` and its `return_count` increases by one. Second, for every `APPLY` allocation the payment ever created, the system writes a `REVERSE` allocation of equal amount bearing the note `nsf-reversal`. Third, each affected charge recomputes its outstanding balance and flips back toward `OPEN` exactly as described in §3.2. Fourth, every `DRAFT` notice covering an affected charge recomputes its demanded amount, and the returned-payment fee is assessed as a new `NSF_FEE` charge on the lease: its amount is the lesser of the requested `nsf_fee_cents` and the property's `nsf_fee_cap_cents`, it is due on the current date, its source is `RETURN`, and its coverage period is the current date itself. Finally, any `PENDING` collections referral on the lease recomputes its referred balance; and if the lease is already `ENDED`, has no collections referral at all, and the reversal leaves the chronological move-out balance greater than zero, a new `PENDING` referral carrying that balance is created on the spot.

A returned payment is not dead. Re-presentment — requesting the posting transition again on a `RETURNED` payment — is permitted once the lease is `ACTIVE` and the payment clears the same two acceptance rules against the current outstanding. The waterfall then re-runs against the live ledger rather than the original target set; in particular, the returned-payment fee charge created by the earlier return is itself a fee-class target waiting to be satisfied. The payment records the new `posted_date` and returns to `POSTED`, completing the cycle `POSTED` → `RETURNED` → `POSTED`, which may repeat for as long as the bank keeps returning the item.

### 3.5. Waivers and the Monthly Waiver Cap

A `PropertyManager` may forgive all or part of a charge's outstanding balance by waiving it, supplying the `amount_cents` to waive and a free-text `reason`. Three guards stand in front of the action. The target charge must be `OPEN` or `PARTIALLY_PAID`; waiving a charge that is `PAID`, `WAIVED`, or `VOID` is rejected with `ERR_CHARGE_NOT_WAIVABLE`. Segregation of duties forbids self-forgiveness: the caller's `X-User-ID` must differ from the charge's `created_by_user_id`, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES` — charges created by the system itself, whose creator is the literal `system`, may be waived by any property manager. And two fiscal limits apply, evaluated in order: the requested amount must not exceed the charge's outstanding balance (`ERR_WAIVER_EXCEEDS_OUTSTANDING`), and the waiver must fit within the property's calendar-month waiver budget (`ERR_WAIVER_CAP_EXCEEDED`).

The monthly budget is computed across the whole property: the sum of all cents waived in the current calendar month, by the server's logical clock, across every charge of every lease belonging to the charge's property, plus the requested amount, must not exceed the property's `monthly_waiver_cap_cents`. A request that lands the month total exactly on the cap is permitted; only exceeding it fails.

The effect of the waiver depends on its size relative to the outstanding balance. A full waiver — one whose amount equals the charge's outstanding balance — adds the amount to the charge's `waived_cents`, drives `outstanding_cents` to zero, and moves the charge to `WAIVED` from either `OPEN` or `PARTIALLY_PAID`. A partial waiver adds to `waived_cents` and reduces `outstanding_cents` but leaves the charge's status untouched. Either way, every `DRAFT` notice covering the charge recomputes its demanded amount, and any `PENDING` collections referral on the lease recomputes its referred balance.

### 3.6. Late Fees and the Delinquency Sweep

Late fees are assessed by the delinquency sweep, an ops-run checkpoint over the logical clock that is restricted to `SystemOps`. A run performs three duties — it assesses late fees, it evaluates the installment schedules of active payment plans, and it cures or expires notices past their deadlines — and it reports its work as six counts: `late_fees_assessed_count`, `installments_marked_missed_count`, `plans_defaulted_count`, `plans_cured_count`, `notices_cured_count`, and `notices_expired_count`. The sweep is idempotent: a repeated run with an unchanged clock changes nothing.

The late-fee duty walks rent charges in `OPEN` or `PARTIALLY_PAID` status on `ACTIVE` leases whose lease-and-period pair does not already carry a non-`VOID` late-fee charge; at most one non-`VOID` `LATE_FEE` may exist per lease and period, which is what makes the sweep safe to repeat. For each candidate, the days late are the calendar days from the charge's `due_date` to the run date, reduced by the lease's `grace_period_days`, and never less than zero. No fee accrues until at least one full day of lateness remains after the grace period. Under a `FLAT` late-fee type, the raw fee is simply the lease's `late_fee_flat_cents`. Under `PERCENT_PLUS_DAILY`, the raw fee is the charge's `amount_cents` multiplied by the lease's `late_fee_percent_bps` and divided by ten thousand, rounded half up to whole cents, plus the lease's `late_fee_daily_cents` for each day late. In both cases the assessed fee is the lesser of the raw fee and the property's `late_fee_cap_cents`, and a fee that lands exactly on the cap is permitted. When the assessed fee is greater than zero, the sweep persists a `LATE_FEE` charge on the lease: due on the run date, stamped with source `SWEEP`, and carrying the same coverage period as the rent charge that spawned it.

The installment duty evaluates every `ACTIVE` payment plan, walking its installments by ascending `sequence_number`. The money counted toward the plan is the net applied cents — `APPLY` allocations minus `REVERSE` allocations — landing on the plan's covered charges from payments whose `posted_date` is on or after the plan's activation date. An installment is marked `PAID` when that running total reaches at least the cumulative scheduled amount through that installment; otherwise it is marked `MISSED` when the current date has passed its due date; otherwise it remains `PENDING`. The plan's `missed_installment_count` is the number of installments marked `MISSED`: when two or more installments are missed, the plan flips from `ACTIVE` to `DEFAULTED` and records the current date as its `defaulted_date`, which anchors the cooling-off rule of §3.8. When every installment is `PAID`, the plan flips from `ACTIVE` to `CURED`.

The notice duty examines notices in `ISSUED` or `SERVED` status. A notice whose covered charges all show zero outstanding, while the current date is still on or before its `cure_deadline_date`, transitions to `CURED` — this holds whether the notice was merely `ISSUED` or already `SERVED`. A notice whose `cure_deadline_date` has passed with any covered charge still showing a positive outstanding balance transitions to `EXPIRED`, again from either `ISSUED` or `SERVED`.

### 3.7. Pay-or-Quit Notices: Drafting, Issuance, and Service

When informal collection fails, the enforcement trail begins with a draft delinquency notice, created by a `LeasingAgent` or `PropertyManager` against an `ACTIVE` lease — creation against a `DRAFT` lease is rejected with `ERR_LEASE_NOT_ACTIVE`, and against an `ENDED` lease with `ERR_LEASE_ALREADY_ENDED`. The payload names the `lease_id`, an ordered list of `charge_ids` covering the charges being demanded, and the optimistic-concurrency field `expected_lease_version` described in §2.8, rejected with `ERR_STALE_VERSION` when the lease has moved on since the client last read it. Every element of `charge_ids` must belong to the named lease; a charge from another lease is rejected with `ERR_CHARGE_NOT_ON_LEASE`. At draft time the notice's lifecycle fields are all unset: `issued_date`, `cure_deadline_date`, `service_method`, `served_date`, `served_by_user_id`, and `cancel_reason` remain null until the issuance, service, or cancellation event that sets them.

A lease carries at most one draft notice at a time. Creating a notice cancels any existing `DRAFT` notice on the same lease — the older draft moves to `CANCELLED` with its `cancel_reason` set to `SUPERSEDED` — and the creation increments the lease's `version`, which is precisely the mutation the optimistic-concurrency guard exists to make observable.

The draft's coverage window is computed from the covered charges: `period_start_date` is the earliest covered charge's period start and `period_end_date` is the latest covered charge's period end, and the window is read as closed calendar days, both endpoints included. The `amount_demanded_cents` is a live figure while the notice remains in `DRAFT`, recomputed on every change to a covered charge — an allocation, a reversal, a waiver, or a dispute adjustment. It is the sum of the covered charges' outstanding balances, plus, for each covered `RENT` charge that still has a positive outstanding balance and does not yet have a non-`VOID` late-fee charge for the same period, a provisional late fee. The provisional fee uses the late-fee formula of §3.6 but evaluates it as of the current date plus the property's `notice_cure_period_days` — it assumes the charge remains unpaid through the cure deadline — and it is never persisted as a charge. A covered rent charge that already carries a non-`VOID` late fee for the period contributes no provisional fee.

Issuance is a `PropertyManager` act that moves the notice from `DRAFT` to `ISSUED`; issuing from any other status is rejected with `ERR_NOTICE_INVALID_TRANSITION`. The lease must still be `ACTIVE`. Because only one open statutory demand may cover a given day, the closed-day coverage window of the issuing notice must not share a single calendar day with any other notice of the same lease in `ISSUED` or `SERVED` status; an overlap is rejected with `ERR_NOTICE_PERIOD_OVERLAP`. At issuance the demanded amount freezes forever at its issued value, `issued_date` is set to the current date, and `cure_deadline_date` becomes the issued date plus the property's `notice_cure_period_days`.

Service documentation follows issuance: a `PropertyManager` records service on an `ISSUED` notice — serving from any other status is rejected with `ERR_NOTICE_INVALID_TRANSITION` — by supplying the statutory `service_method`, one of `PERSONAL`, `POSTED_AND_MAILED`, or `CERTIFIED_MAIL`, and the `served_date`. The served date must satisfy the full window from `issued_date` through `cure_deadline_date`, inclusive at both ends; a date outside that window is rejected with `ERR_NOTICE_SERVICE_WINDOW`. The recording captures the operator as `served_by_user_id`. From there the notice awaits the sweep's verdict — `CURED` if the debt clears in time, `EXPIRED` if it does not — while a draft that never issued may still be cancelled, its `cancel_reason` reading `SUPERSEDED` when a newer draft replaced it or `MOVE_OUT` when the lease ended beneath it. A lease's notices may be listed with a `status` filter.

### 3.8. Payment Plans: Origination, Approval, and Default

A resident who cannot catch up in one payment may be offered a payment plan, drafted against an `ACTIVE` lease by a `LeasingAgent`, a `PropertyManager`, or the `Tenant` on their own lease. The drafting payload names the `lease_id`, the covered `charge_ids` — a snapshot taken at creation, every element of which must belong to the lease and be in `OPEN` or `PARTIALLY_PAID` status, with a foreign element rejected as `ERR_CHARGE_NOT_ON_LEASE` — the requested `installment_count`, the `first_installment_date`, and the optimistic-concurrency field `expected_lease_version`, with a stale lease rejected as `ERR_STALE_VERSION`. The schedule must be sensible: the installment count must lie between two and twelve inclusive, and the first installment date must fall strictly after the current date; either violation is rejected with `ERR_INVALID_INSTALLMENT_SCHEDULE`. Two further exclusivity rules apply at creation. At most one plan per lease may be `ACTIVE` — drafting while an active plan exists is rejected with `ERR_PLAN_EXISTS` — and a lease whose previous plan defaulted is under a cooling-off period: while the number of days since that plan's `defaulted_date` remains less than the property's `plan_cooling_off_days`, a new plan is rejected with `ERR_PLAN_COOLING_OFF`. Like notice drafting, plan drafting is create-with-supersede: any existing `DRAFT` plan on the lease moves to `CANCELLED` with `cancel_reason` `SUPERSEDED`, and the lease's `version` increments.

The plan's money math runs in a pinned order that removes a circular dependency. First, the covered balance is summed from the outstanding balances of the covered charges, evaluated strictly before any fee exists. Second, the setup fee is fixed: when that pre-fee balance is at least the property's `plan_setup_fee_threshold_cents` — a balance exactly equal to the threshold qualifies — the plan's `setup_fee_cents` equals the property's `plan_setup_fee_cents`; otherwise it is zero. A balance one cent below the threshold incurs no fee even though notionally adding the fee would have carried the total past the threshold, because the fee was already fixed at zero. Third, when the fee is greater than zero, a `PLAN_SETUP_FEE` charge is created on the lease, due on the `first_installment_date` and stamped with source `PLAN`. Fourth, the plan's `scheduled_total_cents` is the pre-fee covered balance plus the setup fee.

The schedule itself divides the scheduled total across the installments by whole-cent floor division: each installment's base amount is the scheduled total divided by the installment count, rounded down to whole cents, and the leftover cents are then distributed one cent each to the earliest installments in sequence order. The pinned order — floor the per-installment share first, then distribute the remainder — matters, because summing exact fractional shares and rounding afterward yields a different first installment. The installments are embedded on the plan as an `installments` schedule of entries carrying a `sequence_number`, a `due_date`, an `amount_cents`, and a `status` of `PENDING`, `PAID`, or `MISSED`; the first falls due on `first_installment_date` and each subsequent installment one calendar month after the previous one. The sum of the installment amounts always equals the scheduled total. The plan records its creator as `drafted_by_user_id`; `approved_by_user_id`, `defaulted_date`, and `cancel_reason` remain null until approval, default, or cancellation respectively sets them. The schedule and its running `missed_installment_count` are visible when a single plan is read back; a lease's plans may be listed with a `status` filter.

Approval is a segregated duty: a `PropertyManager` moves the plan from `DRAFT` to `ACTIVE` — approving from any other status is rejected with `ERR_PLAN_INVALID_TRANSITION` — but the approver's `X-User-ID` must differ from the plan's `drafted_by_user_id`, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Approval is also blocked while any notice on the lease stands `SERVED`, rejected with `ERR_ACTIVE_NOTICE_BLOCKS_PLAN`. A successful approval records the approver as `approved_by_user_id`. From there the sweep of §3.6 takes over the plan's fate: two or more missed installments move it to `DEFAULTED` with the current date recorded as `defaulted_date`, full payment moves it to `CURED`, and a move-out underneath it moves it to `CANCELLED` with `cancel_reason` `MOVE_OUT` — a cancellation that also reaches a plan still in `DRAFT`.

### 3.9. Disputes, Move-Out, and Collections Referral

A tenant who believes a charge is wrong files a dispute against it. Filing is `Tenant`-only, and the filer's `X-User-ID` must equal both the supplied `tenant_id` and the lease's `primary_tenant_id`; a mismatch is rejected with `ERR_UNAUTHORIZED`, as is any attempt by a tenant to act on another tenant's lease. The payload names the `lease_id`, the disputed `charge_id` — which must belong to that lease, else `ERR_CHARGE_NOT_ON_LEASE` — and a free-text `reason`. The dispute opens in `OPEN` status with its `reopen_count` at zero and `adjusted_amount_cents` null until an adjusted resolution supplies it. Disputes may be listed with `lease_id`, `charge_id`, `tenant_id`, and `status` filters, and a single dispute may be read by any role.

Resolution belongs to the `PropertyManager` alone — a tenant attempting to resolve is rejected with `ERR_UNAUTHORIZED`. The resolution payload names the transition `action` (`RESOLVE` or, for the filer's second chance described below, `REOPEN`), an `outcome` of `UPHELD` or `ADJUSTED`, and, for an adjusted outcome, the `adjusted_amount_cents`; the resolver may also attach `resolution_notes`, which default to an empty string. Resolving with the outcome `UPHELD` moves the dispute from `OPEN` to `RESOLVED_UPHELD` with the ledger untouched. Resolving with the outcome `ADJUSTED` requires `adjusted_amount_cents`, which must be at least zero and strictly less than the charge's current `amount_cents`; a missing or out-of-range value is rejected with `ERR_INVALID_REQUEST`. An adjustment fires Cascade C: the charge's `amount_cents` is replaced by the adjusted figure — an adjustment to zero sends the charge to `VOID`, whether it stood at `OPEN` or `PARTIALLY_PAID`, and in the latter case the existing applications remain on the books as historical record — its `outstanding_cents` is recomputed, every `DRAFT` notice covering the charge recomputes its demanded amount, and any `PENDING` collections referral on the lease recomputes its referred balance, automatically recalling itself to `RECALLED` with the system-set `recall_reason` `BALANCE_RESOLVED` when that balance has fallen below the property's `collections_threshold_cents`. A partial adjustment — one that leaves the amount above zero — keeps the charge's current status and merely reduces its outstanding balance. Resolving is permitted only from `OPEN` or `REOPENED`; any other status is rejected with `ERR_DISPUTE_INVALID_TRANSITION`.

An upheld verdict is not necessarily final. The filing `Tenant` — and only that tenant, by ownership — may reopen a `RESOLVED_UPHELD` dispute, moving it to `REOPENED` with its `reopen_count` incremented by one. Reopening from any other status is rejected with `ERR_DISPUTE_INVALID_TRANSITION`, and the reopen may be spent only once: a second attempt is rejected with `ERR_DISPUTE_REOPEN_EXHAUSTED`. A reopened dispute resolves again exactly as an open one — `UPHELD` returning it to `RESOLVED_UPHELD`, `ADJUSTED` firing the same cascade — and with the reopen exhausted, the cycle `OPEN` → `RESOLVED_UPHELD` → `REOPENED` → `RESOLVED_*` terminates; `RESOLVED_UPHELD` is then effectively final, and `RESOLVED_ADJUSTED` is always terminal.

Move-out is the lease's final act, performed by a `PropertyManager` supplying a `move_out_date` that must lie on or after the `term_start_date` and no later than the current date. Requesting move-out while the lease is still in `DRAFT` is rejected with `ERR_LEASE_NOT_ACTIVE`; requesting it on an already-ended lease is rejected with `ERR_LEASE_ALREADY_ENDED`. The transition fires Cascade B: the lease moves from `ACTIVE` to `ENDED` and records the `move_out_date`; every `DRAFT` notice on the lease is cancelled with `cancel_reason` `MOVE_OUT`; every plan in `DRAFT` or `ACTIVE` is cancelled with `cancel_reason` `MOVE_OUT`; and a move-out reconciliation is computed whose chronological balance, when greater than zero, produces a `PENDING` collections referral carrying that balance as its `referred_balance_cents` — while a zero balance produces no referral at all. Existing charges are deliberately not voided or prorated at move-out; proration lives only inside the chronological balance variant.

The reconciliation comes in the two variants first met in §3.2. The forward-looking variant is the sum of outstanding balances over the lease's `OPEN` and `PARTIALLY_PAID` charges, counting every open charge at face value, including charges due after the move-out date — an acceleration view of what is owed. The chronological variant answers a different question — what was actually due by the move-out date — and computes it as follows. Charges whose `due_date` lies after the move-out date contribute nothing. Any other charge due on or before the move-out date contributes its outstanding balance, with one exception: a `RENT` charge whose period straddles the move-out — its `period_start_date` on or before the move-out date and the move-out date strictly before its `period_end_date` — contributes a prorated amount instead. The proration multiplies the charge's `amount_cents` by the number of occupied days — the calendar days from the period start to the move-out date, the move-out day itself not counted — and divides by the number of days in the period, counting both the first and the last day; the result is rounded half up to whole cents, then reduced by the charge's waived cents and net applied cents, floored at zero. When the lease has not ended and no move-out date exists, the chronological variant evaluates with the current date standing in for the move-out date and never prorates. A referral's `referred_balance_cents` always uses the chronological variant, and it is recomputed whenever a charge on the lease changes while the referral remains `PENDING`.

The referral itself follows a small lifecycle. When a referral is first created it stands at `PENDING` with `agency_name`, `referred_date`, and `recall_reason` all null. A `PropertyManager` refers a `PENDING` referral by naming the `agency_name`; two gates guard the act — no dispute on the lease may be `OPEN` or `REOPENED` (`ERR_BLOCKING_DISPUTE`), and the referred balance must be at least the property's `collections_threshold_cents`, with a balance exactly equal to the threshold qualifying (`ERR_REFERRAL_THRESHOLD_NOT_MET`). A successful referral records the current date as `referred_date`. From `REFERRED`, the referral may be settled — moving to the terminal `SETTLED` — or recalled with an operator-supplied `recall_reason`, moving to `RECALLED`. A recalled referral is not dead: it may be referred again under the same two gates, refreshing `referred_date` and `agency_name`, completing the cycle `REFERRED` → `RECALLED` → `REFERRED`. The system also recalls on its own behalf: when a recomputation drives a `PENDING` referral's balance below the threshold, the referral moves to `RECALLED` with `recall_reason` `BALANCE_RESOLVED`. Any transition not permitted from the referral's current status — settling while still `PENDING`, or referring an already-`REFERRED` referral — is rejected with `ERR_REFERRAL_INVALID_TRANSITION`. A lease's referrals may be listed with a `status` filter.


## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read, modify, or transition an existing resource return `200 OK`. All paths are mounted under the `/api` prefix as shown. Request payloads, preconditions, and side effects for each operation are defined by the narratives in §2 and §3; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/properties` | Create a property with its statutory caps and policy constants | PropertyManager |
| POST | `/api/tenants` | Register a tenant | LeasingAgent, PropertyManager |
| POST | `/api/leases` | Create a lease in `DRAFT` | LeasingAgent, PropertyManager |
| GET | `/api/leases/{id}` | Read one lease | PropertyManager, LeasingAgent, Tenant, SystemOps |
| GET | `/api/leases` | List leases with filters | PropertyManager, LeasingAgent, Tenant, SystemOps |
| POST | `/api/leases/{id}/transition` | Lease lifecycle: `ACTIVATE` (rejects on half-open term overlap on the same unit) or `MOVE_OUT` (runs the end-of-term cascade) | PropertyManager |
| GET | `/api/leases/{id}/ledger` | Computed reconciliation read: both balance variants plus ledger identity components | PropertyManager, LeasingAgent |
| POST | `/api/leases/{id}/charges` | Manually create a charge (kind restricted to `RENT` or `DAMAGE_FEE`); allowed while the lease is `DRAFT` or `ACTIVE` | LeasingAgent, PropertyManager |
| GET | `/api/leases/{id}/charges` | List charges of a lease | PropertyManager, LeasingAgent, Tenant, SystemOps |
| POST | `/api/charges/{id}/waive` | Waive all or part of a charge's outstanding balance; full waiver flips the charge to `WAIVED` | PropertyManager |
| POST | `/api/payments` | Record a payment in `PENDING` (no allocation yet); tenant callers pay their own lease | Tenant, LeasingAgent |
| GET | `/api/payments/{id}` | Read one payment | PropertyManager, LeasingAgent, Tenant, SystemOps |
| GET | `/api/payments` | List payments with filters | PropertyManager, LeasingAgent, Tenant, SystemOps |
| POST | `/api/payments/{id}/transition` | Payment lifecycle: posting runs the waterfall from `PENDING` or `RETURNED` (re-presentment); returning records an NSF and runs the return cascade | LeasingAgent, PropertyManager |
| GET | `/api/allocations/{id}` | Read one allocation (append-only ledger entry) | PropertyManager, LeasingAgent, Tenant, SystemOps |
| GET | `/api/allocations` | List allocations with filters | PropertyManager, LeasingAgent, Tenant, SystemOps |
| POST | `/api/notices` | Create a pay-or-quit notice in `DRAFT`; supersedes any existing draft notice on the lease; OCC-guarded | LeasingAgent, PropertyManager |
| GET | `/api/leases/{id}/notices` | List notices of a lease | PropertyManager, LeasingAgent, Tenant, SystemOps |
| POST | `/api/notices/{id}/transition` | Notice lifecycle: `ISSUE` freezes the demand and sets the cure deadline; `SERVE` records statutory service documentation | PropertyManager |
| POST | `/api/payment-plans` | Create a payment plan in `DRAFT`; supersedes any existing draft plan on the lease; evaluates the setup fee then splits installments; OCC-guarded | Tenant, LeasingAgent, PropertyManager |
| GET | `/api/leases/{id}/payment-plans` | List payment plans of a lease | PropertyManager, LeasingAgent, Tenant, SystemOps |
| GET | `/api/payment-plans/{id}` | Read one plan including the embedded installment schedule | PropertyManager, LeasingAgent, Tenant, SystemOps |
| POST | `/api/payment-plans/{id}/transition` | Plan lifecycle: `APPROVE` with segregation of duties and the served-notice gate | PropertyManager |
| POST | `/api/disputes` | Tenant files a dispute against a charge on their own lease | Tenant |
| GET | `/api/disputes/{id}` | Read one dispute | PropertyManager, LeasingAgent, Tenant, SystemOps |
| GET | `/api/disputes` | List disputes with filters | PropertyManager, LeasingAgent, Tenant, SystemOps |
| POST | `/api/disputes/{id}/transition` | Dispute lifecycle: `RESOLVE` (outcome `UPHELD` or `ADJUSTED`; an adjustment runs the charge-correction cascade) or `REOPEN` (tenant owner, once) | PropertyManager, Tenant |
| POST | `/api/collections-referrals/{id}/transition` | Referral lifecycle: `REFER` (from `PENDING` or `RECALLED`; gated on open disputes and the threshold), `SETTLE`, `RECALL` | PropertyManager |
| GET | `/api/leases/{id}/collections-referrals` | List collections referrals of a lease | PropertyManager, LeasingAgent, Tenant, SystemOps |
| POST | `/api/delinquency-runs` | Ops-run checkpoint sweep over the logical clock: assesses late fees, evaluates plan installments, cures or expires notices; idempotent at an unchanged clock | SystemOps |
| POST | `/api/_clock/set_current_utc` | Test-driving logical clock; the clock starts at 2026-08-01T00:00:00Z and never falls back to wall-clock time | SystemOps |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. The conditions under which each error is raised are defined in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_LEASE_NOT_ACTIVE` | 409 Conflict |
| `ERR_LEASE_ALREADY_ENDED` | 409 Conflict |
| `ERR_PAYMENT_INVALID_TRANSITION` | 409 Conflict |
| `ERR_CHANNEL_NOT_RETURNABLE` | 409 Conflict |
| `ERR_NOTICE_INVALID_TRANSITION` | 409 Conflict |
| `ERR_NOTICE_SERVICE_WINDOW` | 422 Unprocessable Entity |
| `ERR_NOTICE_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_CHARGE_NOT_WAIVABLE` | 409 Conflict |
| `ERR_CHARGE_NOT_ON_LEASE` | 422 Unprocessable Entity |
| `ERR_WAIVER_EXCEEDS_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_WAIVER_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_PARTIAL_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_OVERPAYMENT_REJECTED` | 422 Unprocessable Entity |
| `ERR_PLAN_EXISTS` | 409 Conflict |
| `ERR_PLAN_COOLING_OFF` | 422 Unprocessable Entity |
| `ERR_PLAN_INVALID_TRANSITION` | 409 Conflict |
| `ERR_INVALID_INSTALLMENT_SCHEDULE` | 422 Unprocessable Entity |
| `ERR_ACTIVE_NOTICE_BLOCKS_PLAN` | 409 Conflict |
| `ERR_BLOCKING_DISPUTE` | 409 Conflict |
| `ERR_REFERRAL_THRESHOLD_NOT_MET` | 422 Unprocessable Entity |
| `ERR_REFERRAL_INVALID_TRANSITION` | 409 Conflict |
| `ERR_DISPUTE_INVALID_TRANSITION` | 409 Conflict |
| `ERR_DISPUTE_REOPEN_EXHAUSTED` | 409 Conflict |
| `ERR_LEASE_TERM_OVERLAP` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
