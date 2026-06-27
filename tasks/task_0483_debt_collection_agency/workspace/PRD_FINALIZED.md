# Debt Collection Agency API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Debt Collection Agency API, a back-office platform that governs the full lifecycle of consumer debt placed with a third-party collection agency under the Fair Debt Collection Practices Act (FDCPA). The system is designed for an industry where a single misstep — a call placed one minute outside the permitted window, a settlement accepted on time-barred debt, a tradeline furnished while a dispute is open — carries real regulatory exposure. Accordingly, the platform is built around a chain of compliance gates that sit between business intent and business action: a creditor may place an account and a collector may want to work it, but the system permits collection activity only when validation notices, dispute windows, communication posture, call cadence, and statute-of-limitations guardrails all allow it.

The platform models the parties and artifacts of collection work as peer resources linked by foreign keys: creditors who own and place debt, consumers who owe it, the accounts that bind them, and the satellites that accumulate around an account over its working life — communication attempts, disputes, payment arrangements, payments, skip traces, bureau furnishings, and bureau disputes. Two financial reconciliations run continuously underneath this activity. The first keeps each account's outstanding balance in agreement with the payments posted and settlements forgiven against it. The second computes the commission the agency has earned, under one of two contractual variants the placing creditor selects. Because regulatory deadlines, call windows, and the statute of limitations are all time-driven, the system runs on a logical clock that test harnesses and automation advance explicitly, so that every deadline and cadence computation is deterministic rather than tied to wall-clock time.

The remainder of this document defines the global contracts every endpoint honors (Section 2), the business workflows and the rules scattered through them (Section 3), the endpoint catalogue (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the user acts. The system recognizes exactly five roles: `Creditor`, `Collector`, `ComplianceOfficer`, `BureauOperator`, and `System`. If either header is missing or malformed, or if `X-User-Role` names a value that is not one of these five roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The roles differ in how `X-User-ID` relates to persisted data. When `X-User-Role` is `Creditor`, `X-User-ID` is the `id` of the acting `Creditor` entity; ownership checks on any resource that references a creditor — for example, an account placed by that creditor — compare the resource's creditor foreign key to `X-User-ID`. The remaining four roles carry an opaque identity. When `X-User-Role` is `Collector`, `ComplianceOfficer`, `BureauOperator`, or `System`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record or log it but does not compare it to any entity's `id`.

The role responsibilities are as follows. A `Creditor` places accounts, recalls them, closes them as uncollectible, and sets the commission terms on its own creditor record. A `Collector` sends validation notices, moves accounts into active work, logs communication attempts, records skip-traces, proposes and accepts and counters and rejects arrangements, and posts and reverses payments. A `ComplianceOfficer` raises, investigates, resolves, and reopens disputes, records consumer cease-communication requests, and furnishes tradelines. A `BureauOperator` furnishes tradelines and opens, resolves, and reopens e-OSCAR bureau disputes. The `System` role sets the logical clock and otherwise reads across all resources. Read endpoints are broadly shared; the precise authorization for each endpoint is given in the table in Section 4.

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

List endpoints are paginated through two query parameters. The `limit` parameter bounds how many items are returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip from the start of the result set and defaults to 0.

Unless an endpoint states otherwise, every list response is sorted by the resource's creation timestamp, `created_at`, in ascending order.

List responses carry the pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Temporal Determinism

All time-sensitive behavior in this system reads from a single logical clock rather than the host wall-clock. At server startup the clock holds the default value `2026-01-01T00:00:00Z`, and before any clock-setting call is made the clock reads exactly that default. The `System` role may set the clock to any supplied ISO 8601 instant; the request carries the target instant in `to_iso8601`, and the response reports the new value as `now`. Setting the clock does not retroactively rewrite stored timestamps, but it does change the answers to every time-derived question: whether an account is time-barred, whether a validation deadline has passed, and how many communication attempts fall inside the trailing cadence window are all recomputed against the current clock whenever a resource is read. Because the entire system is clock-driven, deadlines, call windows, statute-of-limitations status, and cadence counts behave deterministically across a test run.

### 2.5. Common Resource Properties

Every resource in the system carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC value with three fractional digits. All entities in this system — creditors, consumers, accounts, communication attempts, disputes, payment arrangements, payments, skip traces, bureau furnishings, and bureau disputes — additionally carry an `updated_at` timestamp, refreshed to an ISO 8601 UTC value whenever any of the resource's properties change, and a `version`, an integer that begins at its initial value on creation and increments by one on every mutation of the resource. The `version` field underpins the optimistic concurrency control described in Section 2.7. A resource's `updated_at` and `version` advance not only on direct edits but also when a computed field on that resource is recalculated as a side effect of activity elsewhere.

### 2.6. Monetary Precision and Rounding

All monetary amounts in this system are stored and exchanged as integer cents — there are no fractional-cent values and no floating-point currency. Wherever a calculation produces a non-integer number of cents — for example, when a basis-point rate is applied to a balance — the result is rounded to whole cents using the round-half-up method, meaning a value whose fractional part is exactly one-half rounds up to the next whole cent. Commission rates and settlement offers are expressed in basis points, where 10,000 basis points equal 100 percent; a rate of 2,500 basis points therefore means 25.00 percent. Basis-point quantities such as the settlement floor are themselves integers and are not rounded to cents.

### 2.7. Optimistic Concurrency Control

Two operations in this system mutate an account's ledger in ways that depend on the account's exact current state, and both are guarded by optimistic concurrency control against the account's `version`. Recalling an account and reversing a payment each require the caller to supply `expected_account_version` in the request body, carrying the `version` of the account the client last observed. The server compares that value to the account's current `version`. If they do not match — because some other writer has, since the client's last read, posted a payment, accepted a settlement, or otherwise advanced the account — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The intent is that a client cannot recall an account, or reverse a payment, against a ledger it has not actually observed: a prior writer may have changed which arrangements and payments would cascade, so the stale request is refused until the client re-reads the account and retries with the current `version`. Both of these operations, on success, increment the account's `version` by one. No other endpoint accepts or requires `expected_account_version`; endpoints not named here perform no version check.

### 2.8. The Two State Dimensions of an Account

An account is unusual in carrying two independent state machines at once. The first, `work_status`, tracks the placement lifecycle and takes the values `PLACED`, `VALIDATION_SENT`, `WORKING`, `RECALLED`, `CLOSED_PAID`, and `CLOSED_UNCOLLECTIBLE`, of which `CLOSED_PAID` and `CLOSED_UNCOLLECTIBLE` are terminal end-states (and `RECALLED`, once reached, is itself a closed end-state from which no further work-status transition is defined). The second, `contact_status`, tracks the FDCPA communication posture and takes the values `PRE_VALIDATION`, `CONTACTABLE`, `VALIDATION_HELD`, and `CEASED`, the last of which is terminal. These two dimensions evolve largely independently: an account may be `WORKING` on the placement axis while `CEASED` on the communication axis. A handful of operations move both at once — most notably, sending the validation notice advances `work_status` from `PLACED` to `VALIDATION_SENT` and simultaneously advances `contact_status` from `PRE_VALIDATION` to `CONTACTABLE`. Section 3 describes each transition and the role authorized to drive it.

### 2.9. Cascades, Compensation, and Ledger Conservation

Certain operations mutate more than one resource in a single atomic action, and the platform guarantees these cascades run to completion. The governing example is account recall, which cancels the account's live arrangements, voids the payments those arrangements carried, and restores the account ledger by the voided amounts. Each resource touched in a cascade has its own `updated_at` refreshed and, where the resource carries a `version`, its `version` incremented. The account ledger obeys a conservation invariant: across a payment's posting and later reversal or voiding, with no forgiveness in between, the sum of `balance_cents` and `amount_collected_cents` on the account is preserved, because every cent removed from one is added back to the other. Section 3 specifies the exact cascade levels and the order in which they execute.

### 2.10. Existence, Validation, and State Checking Order

Across all endpoints the system applies a fixed evaluation order so that failures surface predictably. The presence and validity of the user-context headers are checked first; a request lacking valid `X-User-ID` and `X-User-Role` is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` before anything else. Authorization is checked next: a known role that is not permitted for the endpoint yields `ERR_FORBIDDEN_FOR_ROLE`. The system then confirms that every referenced resource exists — both identifiers carried in the URL path and foreign keys carried in the body — validated left to right in the order they appear, with any missing reference yielding `ERR_NOT_FOUND`. Only then is the request body checked for well-formedness on write endpoints: required fields must be present, enum fields must carry recognized values, monetary amounts and the original principal must be greater than zero, a settlement offer expressed in basis points must lie between 1 and 10,000 inclusive, and a commission rate in basis points must lie between 0 and 10,000 inclusive; a body that fails any of these yields `ERR_INVALID_REQUEST`. After the body is accepted, state-transition endpoints confirm the target resource is in a state from which the requested transition is defined, rejecting otherwise with `ERR_INVALID_STATE`. Domain-specific guardrails — the cease-communication, validation-hold, call-window, cooldown, cadence, time-barred, settlement-floor, furnishing, and arrangement-linkage rules detailed in Section 3 — are evaluated after these structural checks.

## 3. Business Logic & Workflows

### 3.1. Onboarding the Parties: Creditors and Consumers

The collection relationship begins with two foundational records. A `Creditor` is created by a creditor-role caller and represents the original or owning creditor that places debt with the agency. Its record carries the creditor's `name` and three terms that govern how the agency is paid. The `commission_rate_bps` is the contingency commission rate in basis points, an integer between 0 and 10,000 — for instance, 2,500 means the agency keeps a quarter of what it collects. The `commission_basis` selects which of two commission variants applies to all of this creditor's accounts and is one of `GROSS_OF_FEES` or `NET_OF_FEES`, defaulting to `GROSS_OF_FEES` when omitted. The `expense_recovery_cents` records per-account agency expenses that are deducted before commission is computed under the net variant; it defaults to 0 and is meaningful only under `NET_OF_FEES`.

A `Consumer` is the debtor and may be created by either a creditor-role or a collector-role caller. The consumer record carries a `full_name` and a `timezone_offset_minutes`, the consumer's local-time offset from UTC in minutes — for example, −300 for US Eastern standard time — which defaults to 0 and is the basis for evaluating the lawful calling window described later. A consumer may optionally carry a best-known `phone` and `address`, both of which a skip-trace can later overwrite. Every consumer also carries a system-managed `contactability` flag that is one of `UNKNOWN`, `LOCATED`, or `UNLOCATABLE`; it is set to `UNKNOWN` at creation and is later changed only by skip-trace outcomes.

When a collector records a skip-trace for a consumer, the request names the `consumer_id` being located and a `result` of either `LOCATED` or `NOT_FOUND`, and may carry a `new_phone` and a `new_address`. A `LOCATED` result sets the consumer's `contactability` to `LOCATED` and, where the corresponding new value is provided, overwrites the consumer's `phone` and `address` with `new_phone` and `new_address`. A `NOT_FOUND` result sets the consumer's `contactability` to `UNLOCATABLE` and leaves the contact fields untouched. Skip-trace records are retrievable individually and as a list filterable by `consumer_id`.

### 3.2. Placing an Account and the Statute-of-Limitations Clock

A `Creditor` places a debt by creating an `Account`, naming the `creditor_id` of the owning creditor and the `consumer_id` of the debtor, the `original_principal_cents` owed at placement (which must be greater than zero), the `charge_off_date` on which the original creditor charged off the debt, and the statute-of-limitations parameters. The `sol_years` is the statute-of-limitations length in whole years for the debt's jurisdiction and must be greater than zero. The `sol_anchor_basis` selects which event starts the statute clock and is one of `CHARGE_OFF` or `LAST_PAYMENT`, defaulting to `CHARGE_OFF`.

At placement the account is stamped with a `placement_date` equal to the current clock, its `work_status` is set to `PLACED` and its `contact_status` to `PRE_VALIDATION`. The ledger fields are initialized so that `balance_cents` equals `original_principal_cents`, while `amount_collected_cents` and `amount_settled_forgiven_cents` both start at 0. The account also carries a `last_payment_date`, which is the date of the most recent posted payment and is null until one exists.

The statute-of-limitations verdict is published on the account as the boolean `time_barred` and is recomputed at account creation, on every payment posting, on payment reversal, on settlement acceptance, and whenever the clock advances. The anchor instant is chosen by `sol_anchor_basis`: under `CHARGE_OFF` the anchor is the immutable `charge_off_date`; under `LAST_PAYMENT` the anchor is the account's `last_payment_date`, or the `charge_off_date` if no payment has ever posted. The expiry instant is the anchor plus `sol_years` whole years. The account is time-barred — that is, `time_barred` is true — exactly when the clock is at or after that expiry instant; an instant precisely equal to expiry counts as barred. Because `last_payment_date` is never written backward, a new payment can only move a `LAST_PAYMENT` anchor forward, never rewind it, and the `CHARGE_OFF` anchor never moves at all; this is the re-aging guardrail that keeps the basis choice honest.

### 3.3. The Validation Notice and the Dispute Window

Before active collection may begin, a `Collector` sends the §1692g validation notice on a placed account. This is permitted only while the account has not already had a notice sent — that is, while `validation_notice_sent_at` is null; a repeat attempt is rejected with `ERR_VALIDATION_ALREADY_SENT`. This notice-already-sent guard is evaluated before the requirement that the account be in `work_status` `PLACED`: whenever `validation_notice_sent_at` is non-null the request is rejected with `ERR_VALIDATION_ALREADY_SENT`, taking precedence over the `ERR_INVALID_STATE` rejection of Section 2.10. Only once `validation_notice_sent_at` is confirmed null does the PLACED-state check apply, so an account whose `validation_notice_sent_at` is null but whose `work_status` is not `PLACED` — for instance one recalled or closed uncollectible directly from `PLACED` without a notice ever having been sent — is rejected with `ERR_INVALID_STATE`. Sending the notice records `validation_notice_sent_at` at the current clock and sets the account's `validation_deadline` to that instant plus 30 days, which is the exclusive close of the consumer's dispute window. The same action advances `work_status` from `PLACED` to `VALIDATION_SENT` and `contact_status` from `PRE_VALIDATION` to `CONTACTABLE`.

With the notice sent, the collector moves the account into active collection. Beginning work advances `work_status` from `VALIDATION_SENT` to `WORKING`. Two guardrails gate this transition. If the account's `contact_status` is `CEASED`, the request is rejected with `ERR_CEASE_COMMUNICATION`. And if any `VALIDATION`-type dispute on the account is currently unresolved — meaning a dispute in `OPEN`, `INVESTIGATING`, or `REOPENED` status whose `within_validation_window` is true — the request is rejected with `ERR_VALIDATION_HOLD`, because an in-window validation dispute holds collection until it resolves.

### 3.4. Disputes: Validation Holds, Resolution, and the Reopen Loop

A `ComplianceOfficer` raises a `Dispute` against an account. The request names the `dispute_type`, which is either `VALIDATION`, a §1692g verification request, or `ACCURACY`, a challenge to the balance or ownership. The dispute is stamped with `raised_at` at the current clock and its `within_validation_window` is computed as true when `raised_at` falls strictly before the account's `validation_deadline`. A dispute begins life with `status` of `OPEN` and a null `resolution`. When a `VALIDATION` dispute is raised inside the validation window — that is, when `within_validation_window` is true — it pushes the account's `contact_status` to `VALIDATION_HELD`, pausing collection communication on the account until the dispute resolves in the agency's favor.

The dispute lifecycle proceeds along the states `OPEN`, `INVESTIGATING`, `RESOLVED`, and `REOPENED`, where `RESOLVED` is the terminal-but-revisitable state. A compliance officer may move a dispute from `OPEN` to `INVESTIGATING`. Resolution may be applied either from `OPEN` directly or from `INVESTIGATING`, and in both cases the request must carry a `resolution` of `VERIFIED` or `DELETED`; a missing or invalid resolution is rejected with `ERR_INVALID_REQUEST`. On resolution the dispute moves to `RESOLVED` and its `resolution` is recorded. A `VERIFIED` resolution of a `VALIDATION` dispute lifts the hold, moving the account's `contact_status` from `VALIDATION_HELD` back to `CONTACTABLE` so collection may resume. A `DELETED` resolution — applicable to either dispute type — closes the account: it drives the account's `work_status` to `CLOSED_UNCOLLECTIBLE` and, as part of that closure cascade, transitions every still-open `BureauFurnishing` row for the account to `DELETED`.

A `RESOLVED` dispute may be reopened by a compliance officer; reopening is permitted only from `RESOLVED` status and is otherwise rejected with `ERR_INVALID_STATE`. Reopening clears the `resolution` back to null and moves the dispute to `REOPENED`; if the dispute is a `VALIDATION` dispute whose `within_validation_window` is true, reopening re-applies the hold by pushing the account's `contact_status` back to `VALIDATION_HELD`. From `REOPENED`, the same resolution rules apply as from `INVESTIGATING`: a `resolution` of `VERIFIED` or `DELETED` must be supplied, the dispute returns to `RESOLVED`, and the same downstream effects — lifting the hold on `VERIFIED` `VALIDATION` disputes, closing the account and deleting open furnishings on `DELETED` — apply identically. Disputes are retrievable individually and as a list filterable by `account_id` and `status`.

### 3.5. Logging Contact: Cease, Holds, the Calling Window, Cooldown, and Cadence

Every outbound contact is recorded by a `Collector` as a `CommunicationAttempt` naming the `account_id`, the `channel` (one of `PHONE`, `LETTER`, or `EMAIL`), the `attempted_at` timestamp of the attempt (which must be at or before the current clock), and the `outcome`, one of `LOGGED` for an attempt with no answer, `CONVERSATION` for actually speaking with the consumer, or `CANCELLED` for a scheduled attempt later voided by a cascade. Each attempt carries a computed `counts_toward_cadence` flag, which is true for a `PHONE` attempt with outcome `LOGGED` or `CONVERSATION` and false for any `LETTER` or `EMAIL` attempt and for any `CANCELLED` attempt. Only cadence-counting attempts are subject to the frequency and posture rules below; letters and emails are unrestricted by them.

Logging a cadence-counting attempt runs a gauntlet of FDCPA guardrails. First, if the account's `contact_status` is `CEASED`, the attempt is refused with `ERR_CEASE_COMMUNICATION` — once a consumer has invoked cease-communication, no further cadence-counting contact is permitted. Likewise, if the account's `contact_status` is `VALIDATION_HELD` because an in-window validation dispute is unresolved, the cadence-counting attempt is refused with `ERR_VALIDATION_HOLD`. For a `PHONE` attempt, the system converts `attempted_at` into the consumer's local time by applying the consumer's `timezone_offset_minutes`, and requires that local time to fall at or after 08:00:00 and strictly before 21:00:00; an attempt whose local time is earlier than 8 a.m. or at or after 9 p.m. is rejected with `ERR_OUTSIDE_CALL_WINDOW`. There is also a post-conversation cooldown: once the account has a `last_conversation_at` — the `attempted_at` of its most recent `CONVERSATION`-outcome attempt — any cadence-counting attempt whose `attempted_at` falls at or after `last_conversation_at` and strictly before `last_conversation_at` plus 7 days is rejected with `ERR_POST_CONVERSATION_COOLDOWN`. Finally, the cadence cap limits how often the consumer may be contacted in a rolling week.

The cadence cap is built on a trailing 7-day window. The account publishes `attempts_in_window_count`, the number of cadence-counting communication attempts on the account whose `outcome` is `LOGGED` or `CONVERSATION` and whose `attempted_at` falls strictly after the instant seven days before the clock and at or before the clock itself — a half-open window that excludes its start and includes its end. Logging a new cadence-counting attempt that would push `attempts_in_window_count` above seven within that trailing window is rejected with `ERR_CADENCE_EXCEEDED`: the seventh counting attempt in the window is allowed, and the eighth is refused. When an attempt is successfully logged, the account's `attempts_in_window_count` is recomputed, and if the new attempt's outcome is `CONVERSATION`, the account's `last_conversation_at` is set to that attempt's `attempted_at`. Because the window is anchored to the clock, advancing the clock re-derives `attempts_in_window_count` on read. Communication attempts are retrievable individually and as a list filterable by `account_id`.

A `ComplianceOfficer` records a consumer's cease-communication request at any point in the contact lifecycle. The request drives the account's `contact_status` to `CEASED` from whichever of `PRE_VALIDATION`, `CONTACTABLE`, or `VALIDATION_HELD` it currently holds, and `CEASED` is terminal on the communication axis. Once `CEASED`, every subsequent cadence-counting attempt is refused with `ERR_CEASE_COMMUNICATION`, and beginning work on the account is likewise blocked with the same error.

### 3.6. Arrangements: Plans, Settlements, the Floor, and the Time-Barred Guardrail

A `Collector` proposes a `PaymentArrangement` against an account by naming the `account_id` and the `arrangement_type`, which is either `PLAN` — installments at the full balance — or `SETTLEMENT` — a lump or staged payoff at a percentage of the balance. A settlement carries an `offer_pct_bps`, the offer expressed as basis points of `balance_cents` (for example, 6,000 means 60.00 percent), which is required for a `SETTLEMENT` and ignored for a `PLAN`, and which must lie between 1 and 10,000 inclusive. An arrangement may also carry an `installment_count`, the number of installments, which defaults to 1 and must be at least 1, and an optional `good_through` date, the offer's good-through instant used by the payoff quote. A newly proposed arrangement begins with `status` of `PROPOSED`. The arrangement also carries a computed `settlement_amount_cents`, populated at acceptance, which is the amount that fully satisfies the debt for a settlement.

A proposed arrangement branches. From `PROPOSED` a collector may accept, counter, or reject it. Accepting moves the arrangement from `PROPOSED` to `ACCEPTED` and is the most heavily gated transition. The account must be in `work_status` `WORKING`, or the accept is rejected with `ERR_ACCOUNT_NOT_WORKABLE`. For a `SETTLEMENT`, the account must not be time-barred — that is, accepting a settlement on an account whose `time_barred` is true is rejected with `ERR_TIME_BARRED`; a `PLAN` is not subject to this restriction. Also for a `SETTLEMENT`, the offered `offer_pct_bps` must be at least the computed settlement floor in basis points, and an offer below that floor is rejected with `ERR_SETTLEMENT_BELOW_FLOOR`. When a settlement is accepted, its `settlement_amount_cents` is computed as the account's `balance_cents` multiplied by `offer_pct_bps`, divided by 10,000, rounded half up to whole cents. Acceptance changes no ledger amounts on its own; the debt is satisfied only when payments post against the arrangement.

The settlement floor is computed at accept time for a settlement and depends on three inputs: the debt's age, the account balance tier, and whether the debt has been previously verified. The debt's age in whole days is the number of whole days from the account's `charge_off_date` to the current clock. If that age is under 180 days the age-based floor is 7,000 basis points; if it is 180 days or more but under 730 days the age-based floor is 5,000 basis points; and if it is 730 days or more the age-based floor is 3,000 basis points — fresher debt commands a higher floor. The balance-based floor is 4,000 basis points when the account's `balance_cents` is at least 1,000,000 cents (that is, ten thousand dollars or more) and 6,000 basis points otherwise, so larger balances permit a lower floor. The binding floor is the greater of the age-based and balance-based floors. Finally, if the account has any dispute that is `RESOLVED` with a `resolution` of `VERIFIED`, the floor is raised by 1,000 basis points but capped at 10,000 basis points — verified debt commands a higher floor. The resulting value is the settlement floor against which `offer_pct_bps` is compared.

Countering applies only to a settlement: a collector may move a `SETTLEMENT` from `PROPOSED` to `COUNTERED`, and attempting to counter a `PLAN` is rejected with `ERR_INVALID_STATE`. Countering records the counter, after which a new arrangement may be proposed with a revised `offer_pct_bps`. Rejecting moves an arrangement to `REJECTED` and is permitted from either `PROPOSED` or `COUNTERED`; `REJECTED` is terminal. An accepted arrangement reaches `FULFILLED` automatically once posted payments satisfy it (Section 3.7 describes the fulfillment arithmetic), and `FULFILLED` is terminal. An arrangement may also be `CANCELLED` as a consequence of account recall, and `CANCELLED` is terminal; recall can cancel an arrangement from `PROPOSED`, `ACCEPTED`, or `COUNTERED`. Arrangements are retrievable individually and as a list filterable by `account_id` and `status`.

### 3.7. Payments, the Ledger, Fulfillment, and Auto-Close

A `Collector` posts a `Payment` against an account, naming the `account_id`, the `amount_cents` (which must be greater than zero), and optionally the `arrangement_id` of the arrangement the payment fulfills. When supplied, the `arrangement_id` must reference an `ACCEPTED` arrangement on the same account; a payment whose arrangement reference is to a non-accepted arrangement, or to an arrangement on a different account, is rejected with `ERR_ARRANGEMENT_NOT_ACCEPTED`. A posted payment is stamped with `status` of `POSTED` and `posted_at` at the current clock.

Posting a payment drives the account ledger. The account's `amount_collected_cents` is the sum of `amount_cents` across all of its `POSTED` payments, and the account's `balance_cents` is recomputed as the original principal minus the amount collected minus the amount forgiven, floored at zero — that is, `balance_cents` is the larger of zero and `original_principal_cents` minus `amount_collected_cents` minus `amount_settled_forgiven_cents`. The `amount_settled_forgiven_cents` accumulates the principal forgiven by fulfilled settlements, described below. Each posting also recomputes the account's commission, `last_payment_date`, and `time_barred`, and increments the account's `version` by one.

After a payment posts, the system checks whether it fulfills an accepted arrangement. An `ACCEPTED` arrangement reaches `FULFILLED` automatically when the posted payments tied to it suffice: for a `SETTLEMENT`, when the sum of `amount_cents` across `POSTED` payments carrying that `arrangement_id` reaches or exceeds the arrangement's `settlement_amount_cents`; for a `PLAN`, when that same sum reaches or exceeds the account's balance as of the moment the arrangement was accepted. On fulfillment of a settlement, the account's `amount_settled_forgiven_cents` is increased by the difference between the account balance at the time the settlement was accepted and the `settlement_amount_cents`, and the account's `balance_cents` is driven to zero. Whenever the account's `balance_cents` reaches zero — whether through ordinary payment or through settlement fulfillment — the account auto-closes, its `work_status` moving from `WORKING` to `CLOSED_PAID`, and its commission is recomputed at closure.

A posted payment may be reversed by a `Collector`. Reversal is permitted only while the account's `work_status` is not `RECALLED`, `CLOSED_PAID`, or `CLOSED_UNCOLLECTIBLE`, and is otherwise rejected with `ERR_INVALID_STATE`; the request must also carry `expected_account_version` matching the account's current `version`, failing which it is rejected with `ERR_STALE_VERSION` as described in Section 2.7. Reversal moves the payment from `POSTED` to `REVERSED`, subtracts the payment's `amount_cents` from the account's `amount_collected_cents` and adds it back to `balance_cents` so the ledger is restored, recomputes the account's commission, `last_payment_date`, and `time_barred`, and increments the account's `version` by one. Payments are retrievable individually and as a list filterable by `account_id` and `arrangement_id`.

### 3.8. Recall and Uncollectible Closure: The Cascade

A `Creditor` recalls an account to pull the debt back from the agency. Recall is permitted only when the account's `work_status` is not already `CLOSED_PAID`, `CLOSED_UNCOLLECTIBLE`, or `RECALLED`; otherwise it is rejected with `ERR_INVALID_STATE`. The request must carry `expected_account_version` matching the account's current `version`, or it is rejected with `ERR_STALE_VERSION` (HTTP 412) per Section 2.7. A successful recall increments the account's `version` by one, moves `work_status` to `RECALLED`, and runs a three-level cascade. At the first level, every `PaymentArrangement` on the account whose `status` is `PROPOSED`, `ACCEPTED`, or `COUNTERED` is moved to `CANCELLED`. At the second level, each arrangement just cancelled voids its still-live payments: every payment tied to it that is in `POSTED` status moves to `VOIDED`. At the third level, each voided payment subtracts its `amount_cents` from the account's `amount_collected_cents` and adds it back to `balance_cents`, restoring the ledger. The account's commission is recomputed after the cascade to reflect the restored collections.

A `Creditor` may instead close an account as uncollectible. Closure is permitted only when the account's `work_status` is not already `CLOSED_PAID` or `CLOSED_UNCOLLECTIBLE`, and is otherwise rejected with `ERR_INVALID_STATE`. Closing moves `work_status` to `CLOSED_UNCOLLECTIBLE` and recomputes the account's commission, which is still earned on whatever was collected before closure. The same uncollectible end-state is also reached automatically when an open dispute resolves `DELETED`, as described in Section 3.4; in that automatic path the closure additionally cascades every open `BureauFurnishing` on the account to `DELETED`. Accounts are retrievable individually and as a list filterable by `creditor_id`, `consumer_id`, `work_status`, and `contact_status`.

### 3.9. Commission Reconciliation

The agency's commission on an account, published as `commission_earned_cents`, is recomputed whenever the picture of collections changes: on payment posting, on payment reversal or voiding, on account close, and on account recall. The computation follows the placing creditor's `commission_basis`. The applicable rate is the creditor's `commission_rate_bps` divided by 10,000. Only `POSTED` payments contribute; `REVERSED` and `VOIDED` payments are excluded entirely.

Under the `GROSS_OF_FEES` variant, commission is computed per posted payment and then summed: for each `POSTED` payment on the account, multiply that payment's `amount_cents` by the rate and round the product half up to whole cents, then add those per-payment rounded amounts together — round each line first, then sum. Under the `NET_OF_FEES` variant, the rounding happens once at the end: take the total collected (the sum of `amount_cents` across `POSTED` payments), subtract the creditor's `expense_recovery_cents`, and take the larger of that difference and zero to form the net base; then multiply the net base by the rate and round the single product half up to whole cents. The two variants can yield different totals for the same payments because gross rounds per line while net rounds once after subtracting expenses.

### 3.10. The Payoff Quote

For any arrangement, a payoff quote may be requested. The quote names an `as_of` mode, which is either `QUOTE_DATE` (the default when omitted) or `GOOD_THROUGH`, and the response reports the resulting `payoff_cents` together with the `as_of` mode that produced it. The quote first establishes a base amount: for a `SETTLEMENT` arrangement the base is the account's `balance_cents` multiplied by `offer_pct_bps`, divided by 10,000, rounded half up to whole cents; for a `PLAN` the base is simply the account's current `balance_cents`. Under the `QUOTE_DATE` mode the payoff is exactly that base, with no accrual. Under the `GOOD_THROUGH` mode the payoff adds a per-day administrative fee from the clock to the arrangement's `good_through` date: take the number of whole days from the current clock to `good_through`, computed by flooring the elapsed time to whole days and never going below zero, and add 50 cents — the administrative fee of fifty cents per day — for each of those whole days on top of the base. The same arrangement therefore yields two legitimately different payoff totals depending on the requested `as_of` mode.

### 3.11. Furnishing Tradelines and e-OSCAR Bureau Disputes

A tradeline is furnished to a credit bureau by a `ComplianceOfficer` or a `BureauOperator`, creating a `BureauFurnishing` that names the `account_id` and the `bureau`, one of `EQUIFAX`, `EXPERIAN`, or `TRANSUNION`. Furnishing captures the account's `balance_cents` at that moment into the furnishing's `furnished_balance_cents` and sets the furnishing's `status` to `REPORTED`. Furnishing is guarded: a tradeline may not be furnished for an account whose `work_status` is `RECALLED` or `CLOSED_UNCOLLECTIBLE`, nor for an account that has an unresolved `ACCURACY` or `VALIDATION` dispute, and such an attempt is rejected with `ERR_FURNISH_BLOCKED`. Separately, furnishing is also blocked while the account is under a validation hold — that is, while its `contact_status` is `VALIDATION_HELD` because of an unresolved in-window validation dispute — and that block surfaces as `ERR_VALIDATION_HOLD`. A furnishing's `status` is one of `REPORTED`, `UPDATED`, or `DELETED`. Furnishings are retrievable individually and as a list filterable by `account_id`.

A `BureauOperator` opens an e-OSCAR ACDV dispute on a furnished tradeline, creating a `BureauDispute` that names the `furnishing_id` of the tradeline under dispute. The bureau dispute is stamped with `opened_at` at the current clock and an `investigation_deadline` equal to that instant plus 30 days, the exclusive due date for the furnisher's response. It begins with `status` of `OPEN` and a null `outcome`. The bureau dispute lifecycle runs `OPEN`, `RESOLVED`, and `REOPENED`, with `RESOLVED` as the terminal-but-revisitable state. Resolving a bureau dispute — permitted from `OPEN` or from `REOPENED` — requires an `outcome` in the body of `VERIFIED`, `CORRECTED`, or `DELETED`; a missing or invalid outcome is rejected with `ERR_INVALID_REQUEST`. Resolution moves the dispute to `RESOLVED` and records the `outcome`. A `CORRECTED` outcome moves the referenced furnishing's `status` to `UPDATED` and refreshes its `furnished_balance_cents` to the account's current `balance_cents`; a `DELETED` outcome moves the referenced furnishing's `status` to `DELETED`; a `VERIFIED` outcome leaves the furnishing unchanged. A `RESOLVED` bureau dispute may be reopened by a bureau operator, which is permitted only from `RESOLVED` status and otherwise rejected with `ERR_INVALID_STATE`; reopening clears `outcome` back to null and moves the dispute to `REOPENED`, from which resolving again applies the same outcome rules. Bureau disputes are retrievable individually and as a list filterable by `furnishing_id`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including the state-transition operations that drive an account, dispute, arrangement, payment, or bureau dispute from one state to another, and the clock-setting operation — return a `200 OK` status code. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | System |
| POST | `/creditors` | Create a creditor with commission terms | Creditor |
| GET | `/creditors/{id}` | Get a creditor | Creditor, Collector, ComplianceOfficer, BureauOperator, System |
| POST | `/consumers` | Create a consumer (debtor) | Creditor, Collector |
| GET | `/consumers/{id}` | Get a consumer | Creditor, Collector, ComplianceOfficer, BureauOperator, System |
| POST | `/skip-traces` | Record a skip-trace result for a consumer | Collector |
| GET | `/skip-traces/{id}` | Get a skip-trace record | Collector, ComplianceOfficer, System |
| GET | `/skip-traces` | List skip-trace records (filter by consumer) | Collector, ComplianceOfficer, System |
| POST | `/accounts` | Place a new account (debt) | Creditor |
| GET | `/accounts/{id}` | Get an account with all computed fields | Creditor, Collector, ComplianceOfficer, BureauOperator, System |
| GET | `/accounts` | List accounts (filter by creditor, consumer, status) | Creditor, Collector, ComplianceOfficer, BureauOperator, System |
| POST | `/accounts/{id}/send-validation-notice` | Send the §1692g validation notice | Collector |
| POST | `/accounts/{id}/begin-work` | Move the account into active collection | Collector |
| POST | `/accounts/{id}/cease-communication` | Record a cease-communication request | ComplianceOfficer |
| POST | `/accounts/{id}/recall` | Recall the account; cascade cancel/void/restore | Creditor |
| POST | `/accounts/{id}/close-uncollectible` | Close the account as uncollectible | Creditor |
| POST | `/communication-attempts` | Log a contact attempt | Collector |
| GET | `/communication-attempts/{id}` | Get a communication attempt | Collector, ComplianceOfficer, System |
| GET | `/communication-attempts` | List communication attempts (filter by account) | Collector, ComplianceOfficer, System |
| POST | `/accounts/{id}/disputes` | Raise a dispute against an account | ComplianceOfficer |
| GET | `/disputes/{id}` | Get a dispute | Creditor, Collector, ComplianceOfficer, System |
| GET | `/disputes` | List disputes (filter by account, status) | Creditor, Collector, ComplianceOfficer, System |
| POST | `/disputes/{id}/investigate` | Move a dispute to INVESTIGATING | ComplianceOfficer |
| POST | `/disputes/{id}/resolve` | Resolve a dispute (VERIFIED or DELETED) | ComplianceOfficer |
| POST | `/disputes/{id}/reopen` | Reopen a resolved dispute | ComplianceOfficer |
| POST | `/arrangements` | Propose a payment plan or settlement | Collector |
| GET | `/arrangements/{id}` | Get an arrangement | Creditor, Collector, ComplianceOfficer, System |
| GET | `/arrangements` | List arrangements (filter by account, status) | Creditor, Collector, ComplianceOfficer, System |
| GET | `/arrangements/{id}/payoff-quote` | Compute a payoff quote | Creditor, Collector, ComplianceOfficer, System |
| POST | `/arrangements/{id}/accept` | Accept an arrangement | Collector |
| POST | `/arrangements/{id}/counter` | Counter a proposed settlement | Collector |
| POST | `/arrangements/{id}/reject` | Reject a proposed or countered arrangement | Collector |
| POST | `/payments` | Post a payment to an account | Collector |
| GET | `/payments/{id}` | Get a payment | Creditor, Collector, ComplianceOfficer, System |
| GET | `/payments` | List payments (filter by account or arrangement) | Creditor, Collector, ComplianceOfficer, System |
| POST | `/payments/{id}/reverse` | Reverse a posted payment | Collector |
| POST | `/bureau-furnishings` | Furnish a tradeline to a bureau | ComplianceOfficer, BureauOperator |
| GET | `/bureau-furnishings/{id}` | Get a furnishing | Creditor, Collector, ComplianceOfficer, BureauOperator, System |
| GET | `/bureau-furnishings` | List furnishings (filter by account) | Creditor, Collector, ComplianceOfficer, BureauOperator, System |
| POST | `/bureau-disputes` | Open an e-OSCAR ACDV dispute | BureauOperator |
| GET | `/bureau-disputes/{id}` | Get a bureau dispute | Creditor, Collector, ComplianceOfficer, BureauOperator, System |
| GET | `/bureau-disputes` | List bureau disputes (filter by furnishing) | Creditor, Collector, ComplianceOfficer, BureauOperator, System |
| POST | `/bureau-disputes/{id}/resolve` | Resolve an e-OSCAR dispute | BureauOperator |
| POST | `/bureau-disputes/{id}/reopen` | Reopen a resolved e-OSCAR dispute | BureauOperator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VALIDATION_ALREADY_SENT` | 409 |
| `ERR_CEASE_COMMUNICATION` | 409 |
| `ERR_VALIDATION_HOLD` | 409 |
| `ERR_OUTSIDE_CALL_WINDOW` | 409 |
| `ERR_POST_CONVERSATION_COOLDOWN` | 409 |
| `ERR_CADENCE_EXCEEDED` | 409 |
| `ERR_TIME_BARRED` | 409 |
| `ERR_SETTLEMENT_BELOW_FLOOR` | 409 |
| `ERR_ACCOUNT_NOT_WORKABLE` | 409 |
| `ERR_FURNISH_BLOCKED` | 409 |
| `ERR_ARRANGEMENT_NOT_ACCEPTED` | 409 |
| `ERR_STALE_VERSION` | 412 |
