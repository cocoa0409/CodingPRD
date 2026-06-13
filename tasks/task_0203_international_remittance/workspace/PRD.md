# International Remittance API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the International Remittance API, a back-office platform in the spirit of Wise and Western Union that moves money across borders through a chain of priced, screened, and audited steps. A front-office agent registers the people who send and receive money, prices a transfer against a published mid-market rate, locks that rate for a fixed window, books the transfer, and records the sender's pay-in. A compliance reviewer independently screens every transfer against a sanctions list, holds or clears it, and works any case the screening opens. A back-office payout operator dispatches the funds to the beneficiary's bank, cash-pickup partner, or wallet, reports the result, and — when delivery cannot complete — refunds the sender. A platform administrator configures the corridors, the FX rates, and the sanctions list itself, and drives a logical clock the rest of the system reads as "now".

The platform's defining characteristic is **segregation of duties**: the agent who books and funds a transfer is deliberately not the officer who clears its compliance hold, and neither of them is the operator who dispatches the payout. Money is treated as a conserved quantity — every movement is recorded as a signed ledger entry, reservations against a corridor are made when funds are committed and released when they are delivered or refunded, and the books for a finished transfer balance to a precise, predictable figure. Pricing, sanctions risk, send limits, and refund eligibility each carry their own arithmetic with pinned rounding and inclusive boundaries, because in a remittance business a one-cent or one-point disagreement is a reconciliation failure, not a rounding nicety.

All monetary amounts in this system are expressed in **minor units** of the relevant currency (for example, US cents for `USD`), and all FX rates are expressed in **micro-units** (the true rate scaled by one million). The system never stores fractional minor units; every computed amount is an integer.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint. The business workflows in Section 3 assume everything here.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly four roles, spelled precisely as follows: `PlatformAdmin`, `RemittanceAgent`, `ComplianceOfficer`, and `PayoutOperator`. When a caller's role is well-formed but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

All four roles are **operator identities** rather than persisted parties to a transfer. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any stored entity; the platform administrator configures the system and is never a sender or recipient. When `X-User-Role` is `RemittanceAgent`, `X-User-ID` is likewise an opaque front-office operator identifier; the agent acts on behalf of senders and recipients but is not itself one of them, and the server does not compare `X-User-ID` to any entity's `id`. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque reviewer identifier; the server may record it — for example as `assigned_officer_id` on a `ComplianceCase` — but does not match it against any entity's `id`. When `X-User-Role` is `PayoutOperator`, `X-User-ID` is an opaque back-office identifier, again recorded at most as an audit trace and never used for ownership comparison. Because no role is entity-backed, ownership is established through the foreign-key fields carried in request bodies (such as a recipient's `sender_id`), not by matching the caller against a resource.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a workflow states otherwise, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Most resources in this system are **versioned, mutable entities**: corridors, senders, recipients, quotes, transfers, compliance cases, payout attempts, and refunds. Each of these carries a server-minted `id` (a UUID with no type prefix), a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. Both timestamps are ISO 8601 UTC values with three fractional digits. The `version` begins at 1 on creation and increments by one on every mutation; whenever the `version` advances, `updated_at` is refreshed to the mutating instant.

A small set of resources are **immutable audit records** created once and never modified: `FxRate`, `SanctionsListEntry`, `SanctionsHit`, and `LedgerEntry`. These carry only `id` and `created_at`. They do not carry `updated_at` and do not carry `version`, because nothing ever mutates them after creation.

### 2.5. Hierarchical Consistency and Cross-Entity Cascades

Many operations in this system touch more than one entity inside a single request, and the system reconciles every derived field before the request returns — there is no deferred or background settlement. Three patterns recur. First, a **status bubble**: deciding a compliance case does not merely change the case; it writes the matching `compliance_status` onto the underlying transfer in the same request. Second, an **attempt bubble**: reporting the outcome of a payout attempt sets the attempt's own `outcome` and, in the same step, advances the transfer's `delivery_status`. Third, a **compensating chain**: rejecting a funded, undelivered transfer's compliance case triggers a refund that returns money to the sender and drives the transfer's `delivery_status` to `REFUNDED`. Each entity mutated along such a cascade independently has its `updated_at` refreshed and its `version` incremented; a single request that touches a case and its transfer increments both versions.

The corridor's `reserved_minor` field is the running consistency anchor for committed funds. It is recomputed inside the request that changes a transfer's committed state, never out of band.

### 2.6. Resource Existence and Reference Resolution

Every identifier a request supplies — both path identifiers and foreign keys embedded in the body — must resolve to an existing resource. The system validates these references left-to-right in the order they appear, path identifiers first and then body foreign keys, and rejects the first unresolved reference with `ERR_NOT_FOUND`. A request that names a transfer that does not exist fails on the transfer before any body field is inspected; a request whose path resolves but whose body names a non-existent `recipient_id` fails on that foreign key.

### 2.7. Monetary Precision, Scaling, and Rounding

Every stored amount is an integer in minor units, and every FX rate is an integer in micro-units (the rate scaled by `SCALE_MICRO`, one million). Because amounts are integers, division is the only place rounding arises, and the **rounding direction is pinned per calculation** — the pricing rules in Section 3 floor (round toward zero, discarding any fractional minor or micro unit), while the sanctions name component rounds half up at its points step. Where a calculation specifies that several components are each rounded before being summed, the components are floored independently and only then added; the system never sums first and rounds the total. No calculation in this system uses banker's rounding or any approximation; every boundary is exact.

### 2.8. Send-Limit and Reservation Discipline

A corridor enforces three independent ceilings on the money flowing through it, and a transfer's funding step is the choke point where all three are checked together (Section 3.4 gives the precise arithmetic). A corridor also carries a live `reserved_minor` figure: the sum of send principal across transfers that have been funded on the corridor but not yet delivered or refunded. When a transfer is funded, its principal is added to `reserved_minor`; when that transfer is delivered or refunded, the same principal is subtracted back out, so the reserved figure always reflects in-flight exposure and nothing more.

### 2.9. The Conserved-Funds Ledger

Every movement of money is recorded as a `LedgerEntry` against a transfer, and ledger entries are immutable. Each entry carries a `transfer_id`, an `entry_type`, a signed `amount_minor` expressed in send-currency minor units, and an optional human-readable `memo`. Debits are negative and credits are positive. The `entry_type` is one of `SENDER_DEBIT`, `RECIPIENT_CREDIT`, `FEE_REVENUE`, `REFUND_CREDIT`, or `FEE_REVERSAL`. The ledger is governed by a conservation invariant, described precisely in Section 3.8, that pins the exact net of all entries for a transfer once it reaches a terminal delivery state.

### 2.10. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, each pinned to a specific parent entity's `version`.

Creating a transfer consumes a locked quote, so it is guarded against a stale view of that quote. A create-transfer request must carry `expected_quote_version` carrying the client's last observed `version` of the target `Quote`. If the quote's current `version` differs from `expected_quote_version` — for instance because the same quote was re-locked, advancing its `version`, after the agent last read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so an agent never consumes a quote it has not actually observed in its current form.

Deciding a compliance case is guarded against a stale view of that case. A decide request must carry `expected_case_version` carrying the client's last observed `version` of the target `ComplianceCase`. If the case's current `version` differs — for instance because a request-info / provide-info exchange legitimately advanced the case after the officer loaded its detail — the decision is rejected with `ERR_STALE_VERSION` (HTTP 412), so an officer never clears or rejects a case on the strength of information that has since changed.

No other endpoint takes a version field; OCC applies only to transfer creation and compliance-case decisions.

### 2.11. The Logical Clock

The system reads time from an administrator-controlled logical clock rather than wall-clock time, which lets every time-dependent rule — rate-lock expiry, the rolling send window, and the refund grace period — be exercised deterministically. An administrator may set the clock to an absolute instant by supplying `to_iso8601`, or advance it by supplying a number of `seconds`. Whenever the clock moves, the system re-evaluates rate-lock expiry: any `LOCKED` quote whose expiry instant has been reached is moved to `EXPIRED` before any later read can observe it as still locked.

## 3. Business Logic & Workflows

### 3.1. Configuring the Network: Corridors, Rates, and the Sanctions List

A `PlatformAdmin` lays down the rails before any money moves. A **corridor** is the priced route between two countries, created with a human `name`, an origin `send_country` and destination `receive_country` (each an ISO-3166 alpha-2 code), a `send_currency` and `receive_currency` (each ISO-4217), and the `enabled_payout_methods` it supports — a subset of `BANK`, `CASH_PICKUP`, and `WALLET`. Pricing configuration lives on the corridor: an `fx_margin_bps` margin in basis points applied against the mid-market rate (one basis point is one ten-thousandth), a flat fee component `fee_flat_minor` in send-currency minor units, a percentage fee `fee_pct_bps` in basis points of principal, and a discounted percentage `fee_pct_tier2_bps` that takes over once principal reaches the inclusive threshold `fee_tier_threshold_minor`. The corridor also carries its send-limit configuration: `per_transfer_max_minor` caps a single transfer, `rolling_window_cap_minor` caps cumulative funded send per sender within `rolling_window_hours` (which defaults to 24 hours when omitted), and `rate_lock_ttl_seconds` sets how long a locked rate stays valid (defaulting to 1800 seconds when omitted). On creation a corridor's `status` is `ACTIVE` and its `reserved_minor` is 0. An administrator may later suspend a corridor, moving its `status` to `SUSPENDED`; a `SUSPENDED` corridor blocks new quotes and transfers.

Pricing also needs a live market rate. An administrator publishes an **FX rate** snapshot bound to a corridor by `corridor_id`, carrying a `mid_rate_micro` (the mid-market receive-per-send rate scaled by one million) and an `effective_at` instant from which it prevails. The prevailing rate for a corridor at any moment is the snapshot with the latest `effective_at` that is at or before the current clock; when two snapshots share an `effective_at`, the later-created one wins, and the earlier-created one breaks any remaining tie only by yielding to it. Snapshots are immutable.

The sanctions list is likewise administrator-owned. Each **sanctions list entry** carries a `listed_name` to screen against, a `listed_country`, a `program` code such as an OFAC designation, and two scoring weights: `weight_name_bps`, the contribution of the name-token component (defaulting to 7000 of 10000), and `weight_country_bps`, the contribution of the country-match component (defaulting to 3000 of 10000). List entries are immutable audit records.

### 3.2. Onboarding Parties: Senders and Their Beneficiaries

A `RemittanceAgent` registers a **sender** with a legal `full_name`, a residence `country`, and a `date_of_birth` in year-month-day form; the name and date of birth are the identifiers later screened against the sanctions list. A freshly registered sender starts at `kyc_tier` of `TIER0` and `status` of `ACTIVE`. A sender's KYC tier is not self-asserted: only a `ComplianceOfficer` raises it, after identity verification, by setting `kyc_tier` to `TIER0`, `TIER1`, or `TIER2`. The tier gates how much the sender may move per transfer, as Section 3.4 details. A sender whose `status` is `BLOCKED` — a state reached only through a confirmed sanctions match — may not be the subject of new quotes or transfers; such attempts are rejected with `ERR_SENDER_BLOCKED`.

Each sender owns one or more **recipients** (beneficiaries). An agent creates a recipient under a sender by supplying that sender's `sender_id`, the beneficiary's legal `full_name` and receiving `country`, the `payout_method` (`BANK`, `CASH_PICKUP`, or `WALLET`), and a `payout_account_ref` — the account number, wallet handle, or pickup-partner code appropriate to the method. A new recipient begins with `kyc_status` of `UNVERIFIED`, a `kyc_review_count` of 0, and an empty `kyc_doc_ref`.

A beneficiary must clear KYC before any transfer can be delivered to them, and the review is a small state machine on `kyc_status`. The agent submits documents, which requires a `kyc_doc_ref` in the body — omitting it is rejected with `ERR_KYC_DOC_REQUIRED`. A submission from `UNVERIFIED` records the supplied `kyc_doc_ref` and moves the recipient to `PENDING_REVIEW`. A `ComplianceOfficer` then decides the review by supplying a `decision`: an `APPROVE` decision advances a `PENDING_REVIEW` recipient to `VERIFIED`, while a `REJECT` decision moves it to `REJECTED`. A `REJECTED` beneficiary is not a dead end — the agent may resubmit documents, which again requires `kyc_doc_ref`, records the new reference, and returns the recipient to `PENDING_REVIEW`; this resubmission path additionally increments `kyc_review_count` by one, so the field counts how many times the beneficiary has cycled back into review after a rejection. Each of these transitions increments the recipient's `version`.

### 3.3. Pricing a Send: Quotes and the Rate Lock

Quoting is where the customer-facing price is assembled. A `RemittanceAgent` creates a **quote** by naming the `corridor_id` being priced, the `sender_id` requesting it, the `send_principal_minor` the sender wants delivered net of fee, and the `payout_method` to be used — which must be one of the corridor's `enabled_payout_methods`, or the request is rejected with `ERR_PAYOUT_METHOD_NOT_SUPPORTED`. A new quote is created in `DRAFT` status with its disclosure fields populated provisionally; its `locked_at` and `expires_at` are empty until the rate is locked. A blocked sender cannot be quoted, as noted above.

The rate lock is the commitment moment. An agent locks a `DRAFT` quote, which is permitted only while the corridor is `ACTIVE` — a suspended corridor yields `ERR_CORRIDOR_SUSPENDED` — and only when no other quote for the same sender-and-corridor pair is currently `LOCKED` with an expiry still in the future; an overlapping live lock is rejected with `ERR_RATE_LOCK_OVERLAP`. Locking sets `locked_at` to the current clock and `expires_at` to `locked_at` plus the corridor's `rate_lock_ttl_seconds`, snapshots the prevailing `mid_rate_micro` onto the quote, and computes the four disclosure figures — `locked_rate_micro`, `fee_minor`, `recipient_amount_minor`, and `total_pay_minor` — described next. The lock advances the quote from `DRAFT` to `LOCKED` and increments its `version`.

The disclosed customer rate is the mid-market rate eroded by the provider margin: `locked_rate_micro` is the snapshotted `mid_rate_micro` multiplied by the quantity ten-thousand-minus-`fx_margin_bps`, divided by ten thousand, with any fractional micro-unit floored away. The fee is assembled component-by-component with each part floored independently before summing. The percentage rate to apply is chosen by the tier threshold: if `send_principal_minor` is at or above the corridor's `fee_tier_threshold_minor`, the discounted `fee_pct_tier2_bps` applies; otherwise the standard `fee_pct_bps` applies. The percentage component is `send_principal_minor` multiplied by the chosen basis-point rate, divided by ten thousand, floored to a whole minor unit. The flat component is simply `fee_flat_minor`. The total `fee_minor` is the floored percentage component plus the flat component — each floored on its own, then added, never the sum floored. The disclosed delivery amount is computed margin-first: starting from the already-floored `locked_rate_micro`, `recipient_amount_minor` is `send_principal_minor` multiplied by `locked_rate_micro`, divided by one million, floored to a whole receive-currency minor unit — the margin is applied to the rate first and only then is the principal converted, never the reverse. Finally `total_pay_minor`, the amount the sender pays, is `send_principal_minor` plus `fee_minor`.

Because the lock is time-boxed, a quote that has been read after its window has elapsed is `EXPIRED`. The system auto-expires a `LOCKED` quote the moment the clock reaches or passes its `expires_at`: when the clock is advanced or set, any locked quote at or past expiry transitions to `EXPIRED` before any later read observes it. `DRAFT`, `LOCKED`, `CONSUMED`, and `EXPIRED` are the four quote states; `CONSUMED` and `EXPIRED` are terminal.

### 3.4. Booking and Funding a Transfer

A **transfer** is born when a `RemittanceAgent` consumes a locked quote. The create request supplies the `quote_id` to consume, the `recipient_id` the money is destined for, and `expected_quote_version` for the concurrency check described in Section 2.10. Consuming a quote requires that its `expires_at` is strictly after the current clock; a quote whose window has elapsed is rejected with `ERR_QUOTE_EXPIRED`. On success the quote moves from `LOCKED` to `CONSUMED` (incrementing the quote's `version`), and the new transfer copies `corridor_id`, `sender_id`, `send_principal_minor`, `fee_minor`, `recipient_amount_minor`, and `locked_rate_micro` straight off the quote so the booked figures can never drift from what was disclosed. A transfer carries two independent status axes plus a funding flag: it begins with `funding_status` of `UNFUNDED`, `compliance_status` of `SCREENING`, and `delivery_status` of `PENDING`. It also exposes a computed `refundable_minor` showing what would be returned if it were cancelled at this instant. A blocked sender cannot have a transfer created for them.

Funding records the sender's pay-in and is the gate at which every send limit is enforced. A transfer may be funded only when its `compliance_status` is not `REJECTED` — a rejected transfer cannot be funded and yields `ERR_INVALID_STATE`. Three ceilings are then checked, all with inclusive boundaries (the limit value itself passes; one minor unit beyond it fails). First, the transfer's `send_principal_minor` must not exceed the corridor's `per_transfer_max_minor`, else `ERR_PER_TRANSFER_LIMIT`. Second, `send_principal_minor` must not exceed the sender's KYC-tier ceiling, else `ERR_KYC_TIER_LIMIT`; the ceilings are 50000 minor units (five hundred of the major unit) for `TIER0`, 300000 (three thousand) for `TIER1`, and 1500000 (fifteen thousand) for `TIER2`. Third, the rolling-window check: let the window start be the current clock minus the corridor's `rolling_window_hours`; sum `send_principal_minor` across this sender's other funded transfers on this corridor whose funding ledger debit was created strictly after that window start (the lower bound is exclusive, so an entry exactly at the window start is not counted), add this transfer's `send_principal_minor`, and require the projected total to be at most the corridor's `rolling_window_cap_minor`, else `ERR_ROLLING_WINDOW_LIMIT`.

When all three pass, the transfer's `funding_status` becomes `FUNDED`, the corridor's `reserved_minor` is increased by `send_principal_minor`, and two ledger entries are written: a `SENDER_DEBIT` whose `amount_minor` is the negative of the sum of `send_principal_minor` and `fee_minor` (the sender pays principal plus fee), and a `FEE_REVENUE` whose `amount_minor` is the positive `fee_minor`. The transfer's `version` increments.

### 3.5. Sanctions Screening and Compliance Cases

Screening is a `ComplianceOfficer` responsibility and runs the transfer's compliance axis. Screening computes a `sanctions_score` for the transfer — the best (highest) pairwise match over the transfer's sender and recipient against every sanctions list entry — and routes on the threshold. The clear threshold is a score of 60: a score strictly below 60 auto-clears the transfer, moving `compliance_status` from `SCREENING` to `CLEARED` with no case opened; a score at or above 60 moves `compliance_status` to `HELD`. Each screen increments the transfer's `version`.

The pairwise score for a given party against a given list entry is the sum of a name component and a country component. The name component starts from the overlap between the lowercased, whitespace-split tokens of the party's `full_name` and those of the entry's `listed_name`: the overlap count is divided by the token count of `listed_name` (or by one if that count would be zero) to form a ratio, and the name points are that ratio multiplied by the entry's `weight_name_bps`, divided by 100, rounded half up. The country component contributes the entry's `weight_country_bps` divided by 100 when the party's `country` equals the entry's `listed_country`, and zero otherwise. The two components are added to give a pairwise score on a 0-to-100 scale. The transfer's `sanctions_score` is the maximum pairwise score over every (party, list entry) pair, or 0 when there are no list entries. When two pairs tie for the maximum, the entry created earliest is treated as the opening hit. Screening uses one of two name-matching variants determined by the party's country: under the **strict** variant, applied when the party's `country` is on the high-risk country list, name overlap uses prefix-containment — a listed token counts as overlapping when it is a prefix of one of the party's tokens — which always scores at least as high as the base variant on the same inputs, so a transfer held under strict screening could clear under base; under the **base** variant, applied when the party's `country` is not high-risk, name overlap requires exact token equality and can therefore yield a strictly lower score than strict on identical inputs.

When screening lands on `HELD`, two things happen alongside the status change: the system writes a `SanctionsHit` row for every (subject, list entry) pair whose pairwise score is at or above 60, and it opens a `ComplianceCase`. Each hit carries the `transfer_id`, the matched `list_entry_id`, a `subject_kind` of `SENDER` or `RECIPIENT`, the polymorphic `subject_id` (the sender's or recipient's id according to `subject_kind`), and the computed `score`. Hits are immutable. The opened case carries the `transfer_id`, an `opened_reason` of `SANCTIONS_SCORE`, a denormalized `sanctions_hit_id` pointing at the top-scoring hit, an `info_request_count` of 0, an `assigned_officer_id` naming the officer handling it, and a `status` of `OPEN`. The full hit set for a transfer is discoverable by listing sanctions hits filtered by `transfer_id`; the case's `sanctions_hit_id` is only a back-pointer to the opening hit, not a reverse index. (A case may also be opened with `opened_reason` of `MANUAL`.)

A compliance case is a cyclic workflow with an escalation branch. From `OPEN`, an officer may request more information, which moves the case to `AWAITING_INFO` and increments `info_request_count` by one; an agent then provides the requested information — optionally attaching a `note` — which returns the case to `OPEN`. This `OPEN` → `AWAITING_INFO` → `OPEN` loop may repeat any number of times, and `info_request_count` records how many times it has cycled. From `OPEN`, an officer may also escalate the case to `ESCALATED`, but only when the transfer's `sanctions_score` is at or above the escalation threshold of 85; an escalation attempted below that score is rejected with `ERR_ESCALATION_NOT_WARRANTED`. Each of request-info, provide-info, and escalate increments the case's `version`.

The case is closed by a decision. An officer decides a case by supplying a `decision` of `CLEAR` or `REJECT` together with `expected_case_version` for the concurrency guard. A decision is allowed only from `OPEN` or `ESCALATED`; deciding a case in any other status is rejected with `ERR_INVALID_STATE`, and a stale `expected_case_version` is rejected with `ERR_STALE_VERSION` as described in Section 2.10. A `CLEAR` decision sets the case `status` to `CLEARED` and bubbles `CLEARED` onto the transfer's `compliance_status`. A `REJECT` decision sets the case `status` to `REJECTED` and bubbles `REJECTED` onto the transfer's `compliance_status`; furthermore, if the transfer is currently funded and still pending delivery, the rejection triggers the compensating refund chain (with reason `COMPLIANCE_REJECT`) that drives the transfer's `delivery_status` to `REFUNDED`. Both decisions increment the case's `version` and, through the bubble, the transfer's `version`. `CLEARED` and `REJECTED` are the terminal case states.

### 3.6. Dispatch, Delivery, and Payout Tracking

Once a transfer is funded and cleared, a `PayoutOperator` dispatches it. Dispatch is the entry to the delivery axis and is gated by three preconditions: the transfer must be funded (`funding_status` equal to `FUNDED`, else `ERR_TRANSFER_NOT_FUNDED`); its `compliance_status` must be `CLEARED` (a transfer still under hold yields `ERR_COMPLIANCE_HOLD`); and the beneficiary's `kyc_status` must be `VERIFIED` (else `ERR_RECIPIENT_NOT_VERIFIED`). A dispatch from `delivery_status` of `PENDING` creates a `PayoutAttempt` and moves the transfer to `IN_TRANSIT`. The new attempt copies the recipient's `payout_method`, takes an `outcome` of `PENDING`, and is stamped with an `attempt_index` equal to the count of this transfer's prior attempts plus one (attempts are ordered by `created_at` ascending, so the first is index 1). Dispatch increments the transfer's `version`.

The operator reports the result of an attempt by supplying an `outcome`. Reporting against an attempt is allowed only while that attempt's `outcome` is still `PENDING`, else `ERR_INVALID_STATE`. A `SUCCEEDED` outcome sets the attempt's `outcome` to `SUCCEEDED`, advances the transfer's `delivery_status` to `DELIVERED`, releases the corridor reservation by subtracting `send_principal_minor` from the corridor's `reserved_minor`, and writes a `RECIPIENT_CREDIT` ledger entry whose `amount_minor` is the positive `send_principal_minor`. A `FAILED` outcome sets the attempt's `outcome` to `FAILED`, records the supplied `failure_reason` (one of `INVALID_ACCOUNT`, `PICKUP_EXPIRED`, or `WALLET_REJECTED`), and moves the transfer's `delivery_status` to `FAILED`. Either report increments the transfer's `version`. `DELIVERED` and `REFUNDED` are the terminal delivery states.

A failed delivery may be retried. Dispatching again from `delivery_status` of `FAILED` is permitted only while the count of this transfer's `FAILED` payout attempts is below the maximum of 2; a retry beyond that is rejected with `ERR_MAX_ATTEMPTS_REACHED`. A permitted retry behaves like the first dispatch — it creates a fresh `PayoutAttempt` (`outcome` `PENDING`, `attempt_index` one past the prior count) and returns the transfer to `IN_TRANSIT`, incrementing its `version`. Anyone tracking delivery can list payout attempts filtered by `transfer_id` (and by `outcome`) to follow the chain.

### 3.7. Refunds and Cancellations

A refund returns money to the sender and closes the transfer's delivery axis at `REFUNDED`. Refunds arise three ways, distinguished by `reason`. A `RemittanceAgent` may cancel before dispatch with reason `SENDER_CANCEL`, allowed only while `delivery_status` is `PENDING` (otherwise `ERR_INVALID_STATE`). A `PayoutOperator` may refund a delivery that has exhausted its attempts with reason `DELIVERY_FAILED`, allowed only while `delivery_status` is `FAILED` and only once the count of `FAILED` attempts has reached the maximum of 2 — a refund attempted before attempts are exhausted is rejected with `ERR_ATTEMPTS_NOT_EXHAUSTED`. The third path, reason `COMPLIANCE_REJECT`, is not requested directly but is the compensating chain fired when a funded, pending transfer's case is rejected (Section 3.5). A refund whose reason does not fit the transfer's current `delivery_status` is rejected with `ERR_REFUND_NOT_ALLOWED`. A refund request body names the `transfer_id` and the `reason`; refunds are created already settled, so a refund's `status` is `ISSUED` and that is terminal.

Refund arithmetic splits principal from fee. The principal is always fully returned once the transfer was funded: `principal_refunded_minor` equals the transfer's `send_principal_minor` when `funding_status` is `FUNDED`, and 0 otherwise. The fee treatment is the dual-variant heart of the rule. For a `SENDER_CANCEL` — the sender's own choice to back out — the fee is refunded only if the cancellation falls inside a one-hour grace window: let the funded instant be the `created_at` of the transfer's `SENDER_DEBIT` ledger entry; if the transfer was never funded, `fee_refunded_minor` is 0 (no fee was ever charged); if the current clock is within 3600 seconds of that funded instant (at or below the grace window), `fee_refunded_minor` equals the transfer's `fee_minor`; if the clock is past the grace window, `fee_refunded_minor` is 0 and the provider retains the fee. The same transfer therefore yields two different refund totals depending only on when the sender cancels. For a `COMPLIANCE_REJECT` or a `DELIVERY_FAILED` — neither of which is the sender's fault — the fee is always fully reversed when it was charged: `fee_refunded_minor` equals `fee_minor` when `funding_status` is `FUNDED`, and 0 otherwise, with no grace-window dependence. In every case `total_refunded_minor` is `principal_refunded_minor` plus `fee_refunded_minor`, and the computed `refundable_minor` shown on the transfer reflects what a refund at the current instant would return.

When a refund actually moves money for a funded transfer, it restores the corridor: `reserved_minor` is decreased by `send_principal_minor`, and the system writes a `REFUND_CREDIT` ledger entry for the returned principal and a `FEE_REVERSAL` ledger entry for the returned fee. The transfer's `delivery_status` becomes `REFUNDED` and its `version` increments.

### 3.8. The Ledger Conservation Invariant

The ledger is built so that the books for a finished transfer balance to an exact, predictable figure — there is no approximation and the net is checked by exact integer equality. For any transfer, the net is the sum of `amount_minor` over all its ledger entries. A delivered transfer has written exactly three entries: the `SENDER_DEBIT` of negative principal-plus-fee, the `FEE_REVENUE` of positive fee, and the `RECIPIENT_CREDIT` of positive principal; these net to exactly zero, meaning every minor unit the sender paid in has either reached the recipient or become recognized fee revenue. A refunded transfer that travelled the compensating path has written four entries: the `SENDER_DEBIT` of negative principal-plus-fee, the `FEE_REVENUE` of positive fee, the `REFUND_CREDIT` of positive principal, and the `FEE_REVERSAL` of positive refunded fee; these net to exactly the difference between `fee_minor` and `fee_refunded_minor` — precisely the fee the provider was entitled to keep, which is zero on a fault refund and either zero or the full fee on a sender cancel depending on the grace window. Ledger entries are read-only and discoverable by listing them filtered by `transfer_id` (and by `entry_type`) for conservation audit.

### 3.9. Validation Ordering

When several checks could fail on one request, they are evaluated in a fixed priority so that the most fundamental failure surfaces first. The order is: first, that the `X-User-ID` and `X-User-Role` headers are present and well-formed (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); then that the caller's role is permitted for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`); then that every path identifier and body foreign key resolves to an existing resource, checked left-to-right (`ERR_NOT_FOUND`); then that the body is well-formed — required fields present, enum values valid, and all amounts strictly greater than zero (`ERR_INVALID_REQUEST`); then, on a compliance-case decision, the optimistic-concurrency check that `expected_case_version` matches the case's current `version` (`ERR_STALE_VERSION`); then that the target resource is in a state from which the requested transition is allowed (`ERR_INVALID_STATE`); and only then the domain-specific business rules — corridor suspension, sender block, payout-method support, quote expiry and lock overlap, recipient verification and compliance hold at dispatch, and the per-transfer, KYC-tier, and rolling-window send limits. Thus a request from an unknown role is rejected before its body is examined, and a structurally invalid body is rejected before any business rule runs.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`; operations that modify an existing resource, drive a state transition, or take no resource creation return `200 OK`. The two logical-clock endpoints return `200 OK` with no resource body. The complete request and response semantics for each operation are defined in the Section 3 workflow that owns it; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/corridors` | Create a remittance corridor | `PlatformAdmin` |
| GET | `/corridors/{corridorId}` | Get a corridor | `PlatformAdmin`, `RemittanceAgent`, `ComplianceOfficer`, `PayoutOperator` |
| GET | `/corridors` | List corridors | `PlatformAdmin`, `RemittanceAgent`, `ComplianceOfficer`, `PayoutOperator` |
| POST | `/corridors/{corridorId}/suspend` | Suspend a corridor | `PlatformAdmin` |
| POST | `/fx-rates` | Publish a mid-market rate snapshot | `PlatformAdmin` |
| GET | `/fx-rates/{fxRateId}` | Get an FX rate snapshot | `PlatformAdmin`, `RemittanceAgent` |
| GET | `/fx-rates` | List FX rate snapshots | `PlatformAdmin`, `RemittanceAgent` |
| POST | `/senders` | Register a sender | `RemittanceAgent` |
| GET | `/senders/{senderId}` | Get a sender | `RemittanceAgent`, `ComplianceOfficer` |
| GET | `/senders` | List senders | `RemittanceAgent`, `ComplianceOfficer` |
| POST | `/senders/{senderId}/verify-kyc` | Set a sender's KYC tier | `ComplianceOfficer` |
| POST | `/recipients` | Create a beneficiary | `RemittanceAgent` |
| GET | `/recipients/{recipientId}` | Get a beneficiary | `RemittanceAgent`, `ComplianceOfficer`, `PayoutOperator` |
| GET | `/recipients` | List beneficiaries | `RemittanceAgent`, `ComplianceOfficer`, `PayoutOperator` |
| POST | `/recipients/{recipientId}/submit-kyc` | Submit beneficiary KYC documents | `RemittanceAgent` |
| POST | `/recipients/{recipientId}/decide-kyc` | Approve or reject beneficiary KYC | `ComplianceOfficer` |
| POST | `/quotes` | Create a draft quote | `RemittanceAgent` |
| GET | `/quotes/{quoteId}` | Get a quote with fee + rate disclosure | `RemittanceAgent`, `ComplianceOfficer` |
| GET | `/quotes` | List quotes | `RemittanceAgent`, `ComplianceOfficer` |
| POST | `/quotes/{quoteId}/lock` | Lock the rate, freezing fee + rate | `RemittanceAgent` |
| POST | `/transfers` | Create a transfer by consuming a locked quote | `RemittanceAgent` |
| GET | `/transfers/{transferId}` | Get a transfer with both status axes | `RemittanceAgent`, `ComplianceOfficer`, `PayoutOperator` |
| GET | `/transfers` | List transfers | `RemittanceAgent`, `ComplianceOfficer`, `PayoutOperator` |
| POST | `/transfers/{transferId}/fund` | Record the sender pay-in; enforce send limits | `RemittanceAgent` |
| POST | `/transfers/{transferId}/screen` | Run sanctions screening | `ComplianceOfficer` |
| POST | `/transfers/{transferId}/dispatch` | Dispatch payout | `PayoutOperator` |
| GET | `/compliance-cases/{caseId}` | Get a compliance case | `ComplianceOfficer`, `RemittanceAgent` |
| GET | `/compliance-cases` | List compliance cases | `ComplianceOfficer`, `RemittanceAgent` |
| POST | `/compliance-cases/{caseId}/request-info` | Request more info | `ComplianceOfficer` |
| POST | `/compliance-cases/{caseId}/provide-info` | Supply requested info | `RemittanceAgent` |
| POST | `/compliance-cases/{caseId}/escalate` | Escalate a high-score case | `ComplianceOfficer` |
| POST | `/compliance-cases/{caseId}/decide` | Clear or reject a case | `ComplianceOfficer` |
| POST | `/sanctions-list` | Add a sanctions list entry | `PlatformAdmin` |
| GET | `/sanctions-list/{listEntryId}` | Get a sanctions list entry | `PlatformAdmin`, `ComplianceOfficer` |
| GET | `/sanctions-list` | List sanctions list entries | `PlatformAdmin`, `ComplianceOfficer` |
| GET | `/sanctions-hits/{hitId}` | Get a sanctions hit | `ComplianceOfficer` |
| GET | `/sanctions-hits` | List sanctions hits | `ComplianceOfficer` |
| GET | `/payout-attempts/{attemptId}` | Get a payout attempt | `PayoutOperator`, `RemittanceAgent` |
| GET | `/payout-attempts` | List payout attempts | `PayoutOperator`, `RemittanceAgent`, `ComplianceOfficer` |
| POST | `/payout-attempts/{attemptId}/report-outcome` | Report a payout result | `PayoutOperator` |
| POST | `/refunds` | Issue a refund / cancellation | `RemittanceAgent`, `PayoutOperator` |
| GET | `/refunds/{refundId}` | Get a refund | `RemittanceAgent`, `PayoutOperator`, `ComplianceOfficer` |
| GET | `/refunds` | List refunds | `RemittanceAgent`, `PayoutOperator`, `ComplianceOfficer` |
| GET | `/ledger-entries/{ledgerEntryId}` | Get a ledger entry | `PlatformAdmin`, `ComplianceOfficer` |
| GET | `/ledger-entries` | List ledger entries | `PlatformAdmin`, `ComplianceOfficer`, `RemittanceAgent` |
| POST | `/_clock/set` | Set the system UTC clock | `PlatformAdmin` |
| POST | `/_clock/advance` | Advance the system UTC clock | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CORRIDOR_SUSPENDED` | 409 |
| `ERR_SENDER_BLOCKED` | 409 |
| `ERR_PAYOUT_METHOD_NOT_SUPPORTED` | 409 |
| `ERR_RATE_LOCK_OVERLAP` | 409 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_RECIPIENT_NOT_VERIFIED` | 409 |
| `ERR_KYC_DOC_REQUIRED` | 422 |
| `ERR_COMPLIANCE_HOLD` | 409 |
| `ERR_TRANSFER_NOT_FUNDED` | 409 |
| `ERR_PER_TRANSFER_LIMIT` | 409 |
| `ERR_KYC_TIER_LIMIT` | 409 |
| `ERR_ROLLING_WINDOW_LIMIT` | 409 |
| `ERR_ESCALATION_NOT_WARRANTED` | 409 |
| `ERR_MAX_ATTEMPTS_REACHED` | 409 |
| `ERR_ATTEMPTS_NOT_EXHAUSTED` | 409 |
| `ERR_REFUND_NOT_ALLOWED` | 409 |
