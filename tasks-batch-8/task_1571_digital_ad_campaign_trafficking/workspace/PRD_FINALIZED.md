# Digital Ad Campaign Trafficking API — Product Requirements Document

## 1. Introduction

A media agency runs a digital campaign as a chain of contractual and operational artifacts: an insertion order books the budget, line items carry the targeting and pacing strategy, creatives pass QA and third-party tag implementation before they may serve, and delivery is watched daily against plan. Two measurement stacks — the agency's own ad server and the advertiser-mandated verification tag — rarely agree, and the gap between them has direct revenue consequences. It decides which impressions may be billed, when a make-good is owed, and whether an invalid-traffic finding must ground a line item mid-flight.

This document specifies an API for operating that chain end to end. It covers insertion-order booking through line-item setup and mid-flight optimization, creative QA and tagging, daily delivery snapshots with pacing projections and frequency capping across placements, third-party verification reports evaluated against viewability and invalid-traffic thresholds, make-good negotiation under segregation of duties, period reconciliation against a contractually selected billing basis, and the wrap report with conversion attribution that closes the order. The API serves four desk roles — ad-operations management, trafficking, verification analysis, and billing — and treats the reconciliation ledger and the fraud-hold cascade as first-class concerns rather than afterthoughts.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their desk. The system recognizes exactly four roles. An `AdOpsManager` is the agency ad-operations lead and owns insertion orders, the campaign lifecycle, and the server logical clock. A `Trafficker` owns line-item setup, creative QA and tagging, delivery snapshots, impression events, and mid-flight optimization. A `VerificationAnalyst` files third-party measurement reports and proposes make-goods. A `BillingManager` owns reconciliation, decides make-goods, and produces wrap reports.

A request missing either header, or presenting a role the system does not know, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint — including the per-action role gates on make-good transitions, where one action belongs to the analyst and four belong to the billing manager — is rejected with `ERR_FORBIDDEN` (HTTP 403).

For all four roles — `AdOpsManager`, `Trafficker`, `VerificationAnalyst`, and `BillingManager` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow demands attribution (as `recorded_by_user_id` on a verification report, `proposed_by_user_id` and `decided_by_user_id` on a make-good, `reconciled_by_user_id` and `locked_by_user_id` on a reconciliation), and segregation-of-duties checks compare one recorded `X-User-ID` value against another, but no ownership check ever compares `X-User-ID` to any entity's `id`.

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

List endpoints paginate through two query parameters: `limit`, the maximum number of items returned, defaults to 10 and accepts a minimum of 1 and a maximum of 100; `offset`, the number of items skipped, defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource — insertion orders, line items, creatives, verification reports, make-goods, reconciliations, and wrap reports — carries four system-managed fields: `id`, a server-minted UUID with no type prefix, rendered in the canonical hyphenated 8-4-4-4-12 string form (for example `550e8400-e29b-41d4-a716-446655440000`), which is also how the `id` path parameter of item-level routes is interpreted; `created_at`, an ISO 8601 UTC timestamp with three fractional digits captured at creation; `updated_at`, refreshed on every mutation; and `version`, an integer starting at creation and incrementing by one on every mutation of the resource. Delivery snapshots and impression events are append-only ledger records: they carry only `id` and `created_at`, and both `updated_at` and `version` are absent from them.

### 2.5. The Server Logical Clock

All date- and time-dependent logic — flight-window checks, launch timing, pacing day counts, automatic completion, frequency-cap windows, and default event timestamps — reads a server-maintained logical clock, never the wall clock. At server startup the logical clock reads 2026-08-01T00:00:00Z. An `AdOpsManager` may set it through the clock-setting capability by supplying a `to_iso8601` instant; the response reports the new value as `current_utc`. Once set, the logical clock never falls back to wall-clock time.

### 2.6. Money, Rates, and Rounding Discipline

All monetary amounts are integer cents. Every computed cent value that involves division — a line item's budget, a snapshot's spend, a make-good ceiling, a reconciliation's billable amount — is rounded half up to the nearest whole cent. Measurement rates (`viewability_rate`, `ivt_rate`) and the reconciliation `discrepancy_pct` are rounded half up to four decimal places. Pacing projections are whole impressions, rounded half up. The pacing-alert comparison is an exact real-number comparison with no rounding. Conversion attribution uses largest-remainder rounding so that attributed conversions sum exactly to the reported total.

### 2.7. Optimistic Concurrency on Mid-Flight Edits

`PATCH /line-items/{id}` requires a non-optional `expected_line_item_version` input field carrying the line item's `version` as the client last observed it. If the supplied value does not match the line item's current `version` — because another writer has advanced the version since the client last read the resource — the edit is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting goals, pacing, or caps it has not observed. Endpoints not named here do not accept a version field.

### 2.8. Validation Pipeline and Check Ordering

Every request is evaluated against a fixed pipeline, and a request that would trip several checks is rejected with the error belonging to the earliest one. First, authentication: the `X-User-Role` and `X-User-ID` headers must be present and the role must be known (`ERR_UNAUTHENTICATED`). Second, authorization: the role must be permitted for the endpoint (`ERR_FORBIDDEN`). Third, request-body schema: required fields present, types correct, enum members valid, and cross-field consistency — `viewable_impressions` not exceeding `measured_impressions`, `ivt_impressions` not exceeding `measured_impressions`, `clicks` not exceeding `impressions`, `end_date` on or after `start_date`, `flight_end` on or after `flight_start`, `period_end` strictly after `period_start`, `measured_impressions` greater than zero, and positive amounts wherever an amount is required (`ERR_INVALID_REQUEST`). Fourth, existence: path identifiers are validated left to right, and body foreign-key references — `io_id`, `line_item_id`, `verification_report_id` — must resolve to existing resources; the first missing identifier yields `ERR_NOT_FOUND`. Fifth, optimistic concurrency: `expected_line_item_version` must match the current `LineItem` version (`ERR_STALE_VERSION`). Sixth, state validity: the target resource must be in a valid from-state for the requested action, with terminal states locked against any further transition (`ERR_INVALID_STATE`).

Only after these six stages do domain business rules run, and they run in this catalogue order: the fraud-hold guard (`ERR_FRAUD_HOLD`); the temporal window rules — line-item dates within the order flight (`ERR_FLIGHT_WINDOW_VIOLATION`), launch timing (`ERR_FLIGHT_NOT_STARTED`), snapshot date within the line-item flight (`ERR_SNAPSHOT_OUT_OF_FLIGHT`), reconciliation period overlap (`ERR_RECONCILIATION_OVERLAP`), verification period overlap (`ERR_VERIFICATION_PERIOD_OVERLAP`); the referential guards — tagged-creative presence (`ERR_NO_TAGGED_CREATIVE`), order approval state (`ERR_IO_NOT_APPROVED`), line-item-live (`ERR_LINE_ITEM_NOT_LIVE`), breach presence (`ERR_NO_BREACH`), reconciliations locked (`ERR_RECONCILIATION_NOT_LOCKED`), unresolved make-goods (`ERR_UNRESOLVED_MAKE_GOODS`); segregation of duties (`ERR_SEGREGATION_OF_DUTIES`); duplicate snapshot (`ERR_DUPLICATE_SNAPSHOT`); frequency cap (`ERR_FREQUENCY_CAP_EXCEEDED`); tag and QA payload presence (`ERR_TAG_REQUIRED`); and finally the fiscal checks — the order budget ceiling (`ERR_BUDGET_EXCEEDED`) and the make-good credit ceiling (`ERR_CREDIT_EXCEEDS_BASIS`).

### 2.9. Hierarchical Consistency and Cascading Transitions

Every lifecycle transition is requested by posting to the resource's transition route with an `action` field naming the intended action. The insertion order accepts `APPROVE`, `ACTIVATE`, `COMPLETE`, and `CANCEL`; the line item accepts `TRAFFIC`, `LAUNCH`, `PAUSE`, `RESUME`, `COMPLETE`, `CANCEL`, and `CLEAR_FRAUD`; the creative accepts `SUBMIT_QA`, `PASS_QA`, `FAIL_QA`, `REVISE`, `TAG`, `ACTIVATE`, and `ARCHIVE`; the delivery snapshot accepts `VOID`; the verification report accepts `CLOSE_REPORT`; the make-good accepts `APPROVE`, `REJECT`, `REVISE`, `APPLY`, and `REVERSE`; the reconciliation accepts `RECONCILE`, `LOCK`, and `REOPEN`; and the wrap report accepts `FINALIZE`.

State changes propagate down the order → line item → creative hierarchy so the tree never lies about what is serving. Cancelling an insertion order cancels every one of its line items not already `COMPLETED` or `CANCELLED`, and each of those line-item cancellations itself cascades: every creative of such a line item not already `ARCHIVED` is archived — a cascade two levels deep. Launching a line item flips its `TAGGED` creatives to `LIVE`; pausing a line item pauses its `LIVE` creatives; resuming returns its `PAUSED` creatives to `LIVE`; completing or cancelling a line item archives the creatives still in service. An invalid-traffic breach fires the same pause cascade automatically, and finalizing a wrap report closes the parent order. Every mutation — whether directly requested or produced by a cascade — refreshes `updated_at` and increments `version` by one on each resource it touches, for every resource that carries those fields.

### 2.10. Compensating Actions and Aggregate Invariants

Two operation pairs are exact inverses, and the aggregates they touch must reflect that. Posting a delivery snapshot and later voiding that same snapshot are a compensating pair: after the pair completes, the line item's `delivered_impressions`, `delivered_clicks`, and `delivered_spend_cents` stand exactly where they stood before the post, because aggregates are sums over `POSTED` snapshots only. Applying a credit make-good and later reversing it are likewise paired: after apply followed by reverse of the same make-good, the parent order's `total_applied_credit_cents` returns to its pre-pair value, because only `APPLIED` make-goods count toward it.

## 3. Business Logic & Workflows

### 3.1. Booking the Campaign: Insertion Orders

An `AdOpsManager` opens a campaign by creating an insertion order with the advertiser's display name in `advertiser_name`, the contract budget ceiling `total_budget_cents` (a positive cent amount), and the flight dates `flight_start` and `flight_end`, where the last eligible delivery date must fall on or after the first. The order's `billing_basis` — one of `AGENCY_PLATFORM`, `THIRD_PARTY_TAG`, or `LOWER_OF` — is fixed at booking and later decides which measurement stack the bill follows (§3.6). Two governance thresholds ride on the order and propagate to every verification report filed against its line items: `viewability_threshold_pct`, the minimum acceptable viewability rate, defaults to 0.70 when omitted, and `ivt_threshold_pct`, the maximum tolerable invalid-traffic rate, defaults to 0.02. A new order starts in `DRAFT` with `booked_budget_cents` and `total_applied_credit_cents` both at zero.

`booked_budget_cents` is the running sum of `budget_cents` across the order's line items that are not `CANCELLED`; it is recomputed whenever a line item is created, edited in flight, or cancelled. Approving the order (`DRAFT` → `APPROVED`) requires at least one non-`CANCELLED` line item to exist. Activating it (`APPROVED` → `ACTIVE`) requires at least one of its line items to be `LIVE`. Completing it (`ACTIVE` → `COMPLETED`) is allowed only when the logical current date is strictly later than `flight_end` and every line item has reached `COMPLETED` or `CANCELLED`. Cancelling is permitted from `DRAFT`, `APPROVED`, or `ACTIVE` and fires the depth-2 cascade of §2.9; from `COMPLETED`, `CLOSED`, or `CANCELLED` the action fails the state check with `ERR_INVALID_STATE`. Each of these transitions increments the order's `version` by one. The terminal states are `CANCELLED` and `CLOSED`, and `CLOSED` is reachable only as a side effect of finalizing the wrap report (§3.7) — there is no direct close action on the order.

### 3.2. Line Items: Setup, Launch, and Mid-Flight Optimization

A `Trafficker` builds a line item under an existing order by supplying `io_id`, a display `name`, the contracted `goal_impressions` (greater than zero), the booked `cpm_rate_cents` (greater than zero), `start_date` and `end_date`, and a `pacing_mode` of `EVEN` or `ASAP`. Both dates must sit inside the parent order's flight, and `end_date` must be on or after `start_date`; a violation is rejected with `ERR_FLIGHT_WINDOW_VIOLATION`. Once the parent order has reached `COMPLETED`, `CLOSED`, or `CANCELLED`, creating further line items under it fails the state check with `ERR_INVALID_STATE`. Optional configuration includes `targeting`, a free-form object for geo, device, and daypart constraints that defaults to an empty object, and the frequency-cap pair `frequency_cap_max_impressions` and `frequency_cap_window_hours`; when the cap is omitted the line item runs uncapped, and the rolling window defaults to 24 hours. A new line item starts in `DRAFT` with `fraud_posture` `CLEAR`.

Its `budget_cents` is derived at creation as `goal_impressions` multiplied by `cpm_rate_cents`, divided by 1000, and rounded half up to a whole cent. Booking is a fiscal act: the order's `booked_budget_cents` is recomputed with the new line item included, and if that aggregate would exceed the order's `total_budget_cents`, creation fails with `ERR_BUDGET_EXCEEDED`.

Trafficking moves the line item from `DRAFT` to `TRAFFICKED` and requires at least one of its creatives to be in `TAGGED` status, failing with `ERR_NO_TAGGED_CREATIVE` otherwise. Launching (`TRAFFICKED` → `LIVE`) enforces four guards, evaluated after the general state check and in the pipeline order of §2.8, so a fraud hold surfaces before a flight-timing or approval failure: the parent order must be `APPROVED` or `ACTIVE` (`ERR_IO_NOT_APPROVED`); the logical current date must fall on or after `start_date` and on or before `end_date`, with a launch before the start or after the end rejected as `ERR_FLIGHT_NOT_STARTED`; `fraud_posture` must be `CLEAR` (`ERR_FRAUD_HOLD`); and at least one creative must be `TAGGED` or `LIVE`. A successful launch flips every `TAGGED` creative of the line item to `LIVE`. Pausing (`LIVE` → `PAUSED`) takes every `LIVE` creative down to `PAUSED` with it. Resuming (`PAUSED` → `LIVE`) requires `fraud_posture` `CLEAR` and a logical current date on or before `end_date`, and returns every `PAUSED` creative to `LIVE`.

Completion archives the line item's remaining live creatives. A `Trafficker` completes manually — from `LIVE` or `PAUSED` — only when the logical current date is strictly after `end_date`; the system completes a `LIVE` line item automatically the moment a posted delivery snapshot lifts `delivered_impressions` to meet or exceed `goal_impressions` (§3.4). In both cases every creative in `LIVE` or `PAUSED` transitions to `ARCHIVED`. Cancelling is available from `DRAFT`, `TRAFFICKED`, `LIVE`, or `PAUSED` — directly, or as part of an order-level cancel cascade — archives every creative not already `ARCHIVED`, and drops the line item from the order's `booked_budget_cents` sum, which is recomputed. Every line-item transition increments the line item's `version` by one.

While the line item is `LIVE` or `PAUSED`, a `Trafficker` may adjust `goal_impressions`, `cpm_rate_cents`, `pacing_mode`, `start_date`, `end_date`, `frequency_cap_max_impressions`, or `frequency_cap_window_hours` through the OCC-guarded mid-flight edit described in §2.7; in any other status the edit is refused with `ERR_INVALID_STATE`. The edit recomputes `budget_cents` and the order's `booked_budget_cents` (so `ERR_BUDGET_EXCEEDED` applies again), re-checks changed dates against the order flight (`ERR_FLIGHT_WINDOW_VIOLATION`), and increments `version` by one. Separately, the fraud-clearing action is a self-transition available only from `LIVE` or `PAUSED` and only while `fraud_posture` is `BREACH`: it resets `fraud_posture` to `CLEAR`, leaves the status untouched, and still increments `version` by one.

Reading a line item exposes its delivery aggregates — `delivered_impressions`, `delivered_clicks`, and `delivered_spend_cents`, summed over `POSTED` snapshots — together with the pacing trio `pacing_projection_impressions`, `pacing_projection_trailing_impressions`, and `pacing_alert` defined in §3.4. Line items can be listed and filtered by `io_id` or by `status`.

### 3.3. Creative QA, Tagging, and Activation

A `Trafficker` registers a creative under a line item with `line_item_id`, a `name`, the `asset_url`, and pixel dimensions `width` and `height`, both greater than zero. A new creative lands in `UPLOADED` with `ad_tag` and `qa_failure_reason` both null.

The QA loop begins when the creative is submitted for review (`UPLOADED` → `IN_QA`). A pass moves it to `QA_PASSED`. A fail moves it to `QA_FAILED` and requires a non-empty `qa_failure_reason` in the transition payload — a missing or empty reason is rejected with `ERR_TAG_REQUIRED` — and the reason is stored on the creative. Revision (`QA_FAILED` → `IN_QA`) clears `qa_failure_reason` back to null, and the fail-revise loop may repeat as assets are reworked. Once through QA, tagging (`QA_PASSED` → `TAGGED`) captures the third-party ad tag markup: the transition payload must carry a non-empty `ad_tag`, again enforced with `ERR_TAG_REQUIRED`, and the value is stored on the creative.

Activation (`TAGGED` → `LIVE`) may be requested directly by a `Trafficker`, in which case the parent line item must be `LIVE` (`ERR_LINE_ITEM_NOT_LIVE`) and its `fraud_posture` must be `CLEAR` (`ERR_FRAUD_HOLD`); a line-item launch also activates the line item's `TAGGED` creatives automatically. Creatives never pause or resume on their own — those moves (`LIVE` → `PAUSED` → `LIVE`) happen only as cascades of the parent line item's pause and resume, including the fraud cascade of §3.5. Archiving — a move to `ARCHIVED` — is available manually from any non-terminal state — `UPLOADED`, `IN_QA`, `QA_PASSED`, `QA_FAILED`, `TAGGED`, `LIVE`, or `PAUSED` — and also fires automatically from the line-item cancel and complete cascades. `ARCHIVED` is terminal, and every creative transition increments the creative's `version` by one.

### 3.4. Delivery Snapshots, Pacing, and Frequency Capping

Daily delivery enters the system as snapshots: a `Trafficker` posts `line_item_id`, `snapshot_date`, `impressions` (zero or more), and `clicks` (zero or more, never exceeding `impressions`) for a line item in `LIVE`, `PAUSED`, or `COMPLETED`; against any other status the post fails with `ERR_INVALID_STATE`. The `snapshot_date` must fall inside the line item's `start_date`-to-`end_date` range, failing with `ERR_SNAPSHOT_OUT_OF_FLIGHT` otherwise, and a second snapshot for the same line item and date — regardless of whether the first one was voided — is refused with `ERR_DUPLICATE_SNAPSHOT`. At posting, `spend_cents` is fixed as `impressions` multiplied by the line item's `cpm_rate_cents`, divided by 1000, rounded half up to a whole cent, and the line item's three delivery aggregates are recomputed as sums over `POSTED` snapshots only. When that recompute lifts `delivered_impressions` to at least `goal_impressions` on a `LIVE` line item, the line item completes automatically as described in §3.2.

Voiding is the snapshot's compensating action: a `POSTED` snapshot moves to `VOIDED`, the delivery aggregates are recomputed over `POSTED` snapshots only, and the pacing fields are refreshed. After a post followed by a void of the same snapshot, `delivered_impressions`, `delivered_clicks`, and `delivered_spend_cents` stand exactly where they stood before the pair (§2.10). A snapshot already `VOIDED` rejects a second void with `ERR_INVALID_STATE`.

Two pacing projections accompany every line item read, and both share the same day arithmetic. The total flight length is the whole-day difference between `end_date` and `start_date` plus one, so both boundary days count. Elapsed days are the whole-day difference between the logical current date and `start_date`, clamped so the value never falls below zero and never exceeds the total flight length; remaining days are whatever is left. The lifetime-average projection, `pacing_projection_impressions`, divides `delivered_impressions` by the elapsed days to obtain a daily rate — when no day has elapsed yet, the projection is simply `delivered_impressions` — and projects final delivery as `delivered_impressions` plus the remaining days multiplied by that rate, rounded half up to a whole impression. The trailing variant, `pacing_projection_trailing_impressions`, derives its rate from recent form only: sum the impressions over `POSTED` snapshots dated from two days before the logical current date through the current date — a three-calendar-day window in which days without a snapshot contribute zero — and divide by three; the projection is then `delivered_impressions` plus the remaining days multiplied by that trailing rate, again rounded half up. The `pacing_alert` flag compares delivery against expectation: under `EVEN` pacing the expected delivery to date is `goal_impressions` scaled by the fraction of elapsed days over total flight days, while under `ASAP` the expectation is the full `goal_impressions` from day one; the alert is true when `delivered_impressions` is less than ninety percent of that expectation, evaluated as an exact comparison without rounding.

Frequency capping is enforced per line item and per anonymous user, across all placements of the line item. Recording an impression event takes `line_item_id`, the `user_key` the cap is enforced against, and an optional `occurred_at` that defaults to the server's logical clock when omitted; the line item must be `LIVE`, or the event is refused with `ERR_INVALID_STATE`. When `frequency_cap_max_impressions` is set, the server counts already-persisted events for the same line item and `user_key` whose `occurred_at` lies inside the trailing window that starts `frequency_cap_window_hours` before the current logical time and runs up to but does not include it — an event exactly `frequency_cap_window_hours` old is excluded from the count. If that count has already reached the cap, the new event is rejected with `ERR_FREQUENCY_CAP_EXCEEDED`; a count exactly one below the cap still accepts. When the cap is absent, every event is accepted.

### 3.5. Verification Reports, Fraud Holds, and Make-Goods

A `VerificationAnalyst` files a third-party measurement report with `line_item_id`, the `vendor` — `MOAT`, `IAS`, or `DOUBLEVERIFY` — a measurement period from `period_start` through `period_end` (a closed interval, inclusive at both ends), and the vendor counts `measured_impressions` (greater than zero), `viewable_impressions`, and `ivt_impressions` (each at least zero and at most `measured_impressions`). The line item must not be `DRAFT` or `CANCELLED`, or the filing fails with `ERR_INVALID_STATE`. The new period must not overlap an existing report for the same line item and vendor — because the interval is closed, periods that merely touch at a boundary date already conflict, and the filing is rejected with `ERR_VERIFICATION_PERIOD_OVERLAP`. The filing analyst's `X-User-ID` is captured as `recorded_by_user_id`, and the report opens in `OPEN`.

Assessment is computed once, at creation. `viewability_rate` is `viewable_impressions` divided by `measured_impressions`, and `ivt_rate` is `ivt_impressions` divided by `measured_impressions`, each rounded half up to four decimal places. The report's `assessment` is `BREACH` when `viewability_rate` falls below the parent order's `viewability_threshold_pct` or when `ivt_rate` exceeds the order's `ivt_threshold_pct`; a rate exactly equal to its threshold passes, and a report meeting both thresholds is assessed `PASS`. The report also derives `make_good_max_credit_cents`, the ceiling for credit compensation: first compute the viewability shortfall in impressions as the greater of zero and the result of subtracting `viewable_impressions` from the threshold rate multiplied by `measured_impressions` rounded up to a whole impression; then take the sum of `ivt_impressions` and that shortfall, multiply by the line item's `cpm_rate_cents`, divide by 1000, and round half up to a whole cent.

When — and only when — `ivt_rate` exceeds the order's invalid-traffic threshold, filing the report fires the fraud cascade: the line item's `fraud_posture` becomes `BREACH`, a `LIVE` line item drops to `PAUSED` automatically, and every `LIVE` creative under it pauses with it. While the breach stands, launch, resume, and creative activation are refused with `ERR_FRAUD_HOLD` until a `Trafficker` clears the hold through the self-transition of §3.2.

Compensation takes the form of a make-good, proposed by a `VerificationAnalyst` against a report whose `assessment` is `BREACH` and whose status is still `OPEN`; proposing against a passing report or a closed one fails with `ERR_NO_BREACH`. The proposal names the `verification_report_id`, a `kind` of `CREDIT` or `BONUS_IMPRESSIONS`, and the matching amount: `credit_cents` is required when the kind is `CREDIT`, must be greater than zero, and may not exceed the report's `make_good_max_credit_cents` (`ERR_CREDIT_EXCEEDS_BASIS`); `bonus_impressions` is required when the kind is `BONUS_IMPRESSIONS` and must be greater than zero. Both amount fields default to null when not supplied. The proposal lands in `PROPOSED` with `proposed_by_user_id` set to the proposing analyst's `X-User-ID`.

Decisions belong to a `BillingManager`, and segregation of duties forbids the proposer from deciding their own proposal: an approval or rejection whose `X-User-ID` equals `proposed_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES`. Approval moves the make-good from `PROPOSED` to `APPROVED`, rejection moves it to `REJECTED`, and both record the decider in `decided_by_user_id`. A `REJECTED` make-good is not final: the analyst may revise it back to `PROPOSED`, which clears `decided_by_user_id` to null, and the propose-reject-revise loop may repeat. Applying a decided credit (`APPROVED` → `APPLIED`) brings its `credit_cents` into the parent order's `total_applied_credit_cents` — the sum of `credit_cents` over `APPLIED` make-goods whose reports trace back to the order's line items — and reversing (`APPLIED` → `REVERSED`) takes it back out, restoring the pre-pair total exactly (§2.10). The role gates on this resource are per action: revise belongs to the `VerificationAnalyst`; approve, reject, apply, and reverse belong to the `BillingManager`; the wrong role draws `ERR_FORBIDDEN`. Every make-good transition increments its `version` by one.

A report may be closed (`OPEN` → `CLOSED`) only once every make-good filed against it has reached a terminal state — `REJECTED`, `APPLIED`, or `REVERSED`; while any related make-good is still `PROPOSED` or `APPROVED`, closure is blocked with `ERR_UNRESOLVED_MAKE_GOODS`. Closing increments the report's `version` by one. Reports can be listed and filtered by `line_item_id`.

### 3.6. Reconciliation and the Billing Basis

For each billing period, a `BillingManager` opens a reconciliation with `line_item_id`, `period_start`, `period_end`, and the `third_party_impressions` counted by the advertiser's tag for that period (zero or more). The period is a half-open interval: `period_start` is inclusive and `period_end` exclusive, so adjacency is allowed — one reconciliation's `period_end` may equal the next one's `period_start` without conflict — while any true overlap with an existing reconciliation of the same line item is rejected with `ERR_RECONCILIATION_OVERLAP`. The record opens in `OPEN` with `agency_impressions` computed immediately as the sum of `impressions` over the line item's `POSTED` snapshots whose `snapshot_date` falls inside the half-open period. Until the reconcile action runs, `discrepancy_pct`, `billing_impressions`, and `billable_cents` remain null.

Reconciling (`OPEN` → `RECONCILED`) recomputes `agency_impressions` from the currently posted snapshots in the period, then derives `discrepancy_pct`: the difference between `third_party_impressions` and `agency_impressions` divided by `agency_impressions`, rounded half up to four decimal places; when the agency number is zero, `discrepancy_pct` is null. The billable quantity `billing_impressions` then follows the parent order's `billing_basis`. Under `AGENCY_PLATFORM` it is the agency ad-server number, whatever the tag counted. Under `THIRD_PARTY_TAG` it is the third-party tag number, whatever the agency counted. Under `LOWER_OF` it is zero when `agency_impressions` is zero; otherwise it is the smaller of the two numbers only when the absolute value of `discrepancy_pct` exceeds ten percent, and the agency number when the discrepancy stays within that tolerance. `billable_cents` is then `billing_impressions` multiplied by the line item's `cpm_rate_cents`, divided by 1000, rounded half up to a whole cent, and the reconciling manager's `X-User-ID` is recorded as `reconciled_by_user_id`.

Locking (`RECONCILED` → `LOCKED`) is the point of no return and carries two guards. Segregation of duties requires the locking manager's `X-User-ID` to differ from `reconciled_by_user_id`, enforced with `ERR_SEGREGATION_OF_DUTIES`. And no make-good on a verification report of this line item whose measurement period overlaps the reconciliation period may still be `PROPOSED` or `APPROVED`; an outstanding proposal or approval blocks the lock with `ERR_UNRESOLVED_MAKE_GOODS`. The locking manager is recorded in `locked_by_user_id`. A reconciliation may also be reopened (`RECONCILED` → `OPEN`), which clears `reconciled_by_user_id` to null and lets the period be restated and reconciled again — the reopen loop may repeat. Every reconciliation transition increments its `version` by one. Reconciliations can be listed and filtered by `line_item_id` or `status`.

### 3.7. Wrap Reports, Attribution, and Campaign Close

Once an order is `COMPLETED`, a `BillingManager` generates its wrap report by naming `io_id`, an `attribution_model` of `LINEAR_CLICKS` or `VIEW_WEIGHTED`, and the `total_conversions` to attribute (zero or more). Generation requires the order to be `COMPLETED` — any other status fails with `ERR_INVALID_STATE` — and every reconciliation across the order's line items to be `LOCKED`, or the request is refused with `ERR_RECONCILIATION_NOT_LOCKED`. The report is born in `DRAFT` with all totals computed at generation time: `total_delivered_impressions` and `total_spend_cents` sum `delivered_impressions` and `delivered_spend_cents` across the order's line items that are not `CANCELLED`; `total_billable_cents` sums `billable_cents` over only the `LOCKED` reconciliations of those line items, with each reconciliation's cent value rounded first and the rounded values then summed; `total_applied_credit_cents` copies the order's `total_applied_credit_cents` at generation time; and `net_billable_cents` is `total_billable_cents` minus `total_applied_credit_cents`, floored at zero so that heavy credits never turn the bill negative.

Attribution distributes `total_conversions` across those same non-`CANCELLED` line items into the `attribution` array, one entry per line item carrying `line_item_id`, `weight`, and `attributed_conversions`. Under `LINEAR_CLICKS` a line item's weight is its `delivered_clicks` divided by the summed delivered clicks of all participating line items. Under `VIEW_WEIGHTED` the weight comes from the vendor side instead: the sum of `viewable_impressions` over all of the line item's verification reports, regardless of their assessment, divided by that same total across the participating line items — so the two models can diverge on identical delivery data. When the relevant denominator is zero, every participating line item takes an equal weight of one divided by the number of line items. Each weight multiplies `total_conversions` into a raw share, and largest-remainder rounding converts the raw shares into integers that sum exactly to `total_conversions`; ties on fractional remainder are broken in favor of the line item created earlier, ordered by `created_at` ascending.

Finalizing the report (`DRAFT` → `FINALIZED`) locks those stored values, increments the report's `version` by one, and — as its system side effect — moves the parent insertion order from `COMPLETED` to `CLOSED`, ending the campaign lifecycle. Wrap reports can be listed and filtered by `io_id`.

## 4. Endpoint Definitions

Operations that create a new resource — an insertion order, line item, creative, snapshot, impression event, verification report, make-good, reconciliation, or wrap report — return `201 Created`. Operations that modify an existing resource, including all lifecycle transitions, the mid-flight line-item edit, and the clock-setting operation, return `200 OK`. Single-resource reads and list endpoints return `200 OK`. Request and response field semantics for every route are governed by §2 and §3 rather than restated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock (test-driving; startup default 2026-08-01T00:00:00Z, never falls back to wall clock) | AdOpsManager |
| POST | `/insertion-orders` | Create an insertion order | AdOpsManager |
| GET | `/insertion-orders/{id}` | Get one insertion order | AdOpsManager, Trafficker, VerificationAnalyst, BillingManager |
| POST | `/insertion-orders/{id}/transition` | IO lifecycle: APPROVE, ACTIVATE, COMPLETE, CANCEL | AdOpsManager |
| POST | `/line-items` | Create a line item with targeting, pacing, and frequency-cap configuration | Trafficker |
| GET | `/line-items` | List line items; filterable by `io_id` and `status` | AdOpsManager, Trafficker, VerificationAnalyst, BillingManager |
| GET | `/line-items/{id}` | Get one line item, including computed delivery and pacing fields | AdOpsManager, Trafficker, VerificationAnalyst, BillingManager |
| PATCH | `/line-items/{id}` | Mid-flight optimization edit; OCC-guarded | Trafficker |
| POST | `/line-items/{id}/transition` | Line item lifecycle: TRAFFIC, LAUNCH, PAUSE, RESUME, COMPLETE, CANCEL, CLEAR_FRAUD | Trafficker |
| POST | `/creatives` | Upload a creative asset under a line item | Trafficker |
| GET | `/creatives` | List creatives; filterable by `line_item_id` and `status` | AdOpsManager, Trafficker, VerificationAnalyst, BillingManager |
| GET | `/creatives/{id}` | Get one creative | AdOpsManager, Trafficker, VerificationAnalyst, BillingManager |
| POST | `/creatives/{id}/transition` | Creative QA and trafficking lifecycle: SUBMIT_QA, PASS_QA, FAIL_QA, REVISE, TAG, ACTIVATE, ARCHIVE | Trafficker |
| POST | `/delivery-snapshots` | Post a daily agency delivery snapshot for a line item | Trafficker |
| GET | `/line-items/{id}/delivery-snapshots` | List delivery snapshots of a line item, all statuses | AdOpsManager, Trafficker, VerificationAnalyst, BillingManager |
| POST | `/delivery-snapshots/{id}/transition` | VOID a snapshot, removing it from all aggregates | Trafficker |
| POST | `/impression-events` | Record a single impression for frequency-cap enforcement across placements | Trafficker |
| GET | `/line-items/{id}/impression-events` | List impression events of a line item; filterable by `user_key` | AdOpsManager, Trafficker, VerificationAnalyst, BillingManager |
| POST | `/verification-reports` | File a third-party verification report; assessment and fraud cascade computed at creation | VerificationAnalyst |
| GET | `/verification-reports` | List verification reports; filterable by `line_item_id` | AdOpsManager, Trafficker, VerificationAnalyst, BillingManager |
| GET | `/verification-reports/{id}` | Get one verification report | AdOpsManager, Trafficker, VerificationAnalyst, BillingManager |
| POST | `/verification-reports/{id}/transition` | CLOSE_REPORT: close an OPEN report once all make-goods are terminal | VerificationAnalyst |
| POST | `/make-goods` | Propose a make-good (credit or bonus impressions) against a BREACH report | VerificationAnalyst |
| GET | `/make-goods` | List make-goods; filterable by `verification_report_id` and `status` | AdOpsManager, Trafficker, VerificationAnalyst, BillingManager |
| GET | `/make-goods/{id}` | Get one make-good | AdOpsManager, Trafficker, VerificationAnalyst, BillingManager |
| POST | `/make-goods/{id}/transition` | APPROVE, REJECT, APPLY, REVERSE (BillingManager); REVISE (VerificationAnalyst) | BillingManager, VerificationAnalyst |
| POST | `/reconciliations` | Open a third-party tag reconciliation for a line item and period | BillingManager |
| GET | `/reconciliations` | List reconciliations; filterable by `line_item_id` and `status` | AdOpsManager, Trafficker, VerificationAnalyst, BillingManager |
| GET | `/reconciliations/{id}` | Get one reconciliation | AdOpsManager, Trafficker, VerificationAnalyst, BillingManager |
| POST | `/reconciliations/{id}/transition` | RECONCILE, LOCK, REOPEN | BillingManager |
| POST | `/wrap-reports` | Generate the campaign wrap report with attribution for a COMPLETED insertion order | BillingManager |
| GET | `/wrap-reports` | List wrap reports; filterable by `io_id` | AdOpsManager, Trafficker, VerificationAnalyst, BillingManager |
| GET | `/wrap-reports/{id}` | Get one wrap report | AdOpsManager, Trafficker, VerificationAnalyst, BillingManager |
| POST | `/wrap-reports/{id}/transition` | FINALIZE the wrap report; closes the parent insertion order | BillingManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_FRAUD_HOLD` | 409 |
| `ERR_FLIGHT_WINDOW_VIOLATION` | 422 |
| `ERR_FLIGHT_NOT_STARTED` | 422 |
| `ERR_SNAPSHOT_OUT_OF_FLIGHT` | 422 |
| `ERR_RECONCILIATION_OVERLAP` | 409 |
| `ERR_VERIFICATION_PERIOD_OVERLAP` | 409 |
| `ERR_NO_TAGGED_CREATIVE` | 409 |
| `ERR_IO_NOT_APPROVED` | 409 |
| `ERR_LINE_ITEM_NOT_LIVE` | 409 |
| `ERR_NO_BREACH` | 409 |
| `ERR_RECONCILIATION_NOT_LOCKED` | 409 |
| `ERR_UNRESOLVED_MAKE_GOODS` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_DUPLICATE_SNAPSHOT` | 409 |
| `ERR_FREQUENCY_CAP_EXCEEDED` | 422 |
| `ERR_TAG_REQUIRED` | 400 |
| `ERR_BUDGET_EXCEEDED` | 422 |
| `ERR_CREDIT_EXCEEDS_BASIS` | 422 |
