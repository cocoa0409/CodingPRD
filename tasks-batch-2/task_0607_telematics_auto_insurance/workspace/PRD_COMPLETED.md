# Telematics Auto Insurance API — Product Requirements Document

## 1. Introduction

This document specifies the Telematics Auto Insurance API, a usage-based motor insurance platform in the spirit of Root and Progressive Snapshot. Rather than pricing a driver from static demographic proxies, the platform earns its premium from how a person actually drives: a prospective customer first completes a short test-drive scoring period during which telematics trips — each carrying braking, speeding, phone-use, and crash micro-events — are captured and scored, and that score is locked into a binding quote. Once the quote is bound into a policy, the system continues to recompute the driver's operational risk from every accepted trip, bills a mileage-based premium each billing period, sweeps earned safe-driving discounts out of a banking ledger, recalculates the premium at renewal, and — when a hard crash is detected mid-trip — automatically opens a First Notice Of Loss claim and hands it to a claims adjuster.

The platform must reconcile several concerns that pull against one another. Pricing is forward-looking during the test drive but lifetime-cumulative once a policy is live, so the same trips score differently before and after binding. Privacy is a first-class right: a driver may opt out of telematics capture at any moment, and that opt-out must cascade across every active policy the driver holds, suspending all further capture until it is reversed. Money must be conserved to the cent: a discount bank never goes negative, lifetime safe miles are restored when an accepted trip is voided, and a settled billing period cannot be retroactively disturbed. The remainder of this document defines the global contracts every endpoint shares (Section 2) and then the detailed business workflows that govern each entity's lifecycle (Section 3), before cataloguing the concrete endpoints (Section 4) and error codes (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated with two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_USER_CONTEXT`. The system recognizes exactly three roles: `DriverUser`, `UnderwritingOps`, and `ClaimsAdjuster`. When a request is well-formed but the declared role is not permitted to perform the requested operation, the system responds with `ERR_FORBIDDEN_ROLE`.

The `DriverUser` role represents the insured driver and is entity-backed. When `X-User-Role` is `DriverUser`, `X-User-ID` is the `id` of the acting `Driver`; ownership checks on any resource that references a `Driver` compare the resource's `driver_id` (resolved through its chain — for example a trip resolves through its policy or enrollment to a driver, a claim through its policy to a driver) to `X-User-ID`. A `DriverUser` who acts on a driver-scoped resource that resolves to a different driver is rejected with `ERR_NOT_RESOURCE_OWNER`. This ownership rule guards every `DriverUser` write endpoint whose resource chain resolves to a `driver_id` — the enrollment, quote, trip, privacy-consent, and claim operations.

The `UnderwritingOps` role owns the configuration and contractual side of the business: rate plans, quote generation, quote and enrollment expiry, policy binding, the policy lifecycle and billing periods, statements, renewals, trip voiding, and the logical test-drive clock. When `X-User-Role` is `UnderwritingOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`. The `ClaimsAdjuster` role owns the claim First Notice Of Loss lifecycle — triage, close, and reopen — and may also file manual claims. When `X-User-Role` is `ClaimsAdjuster`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless an endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in the system carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. The `updated_at` field, of the same format, records the most recent modification and is refreshed on every mutation. The `version` field is an integer that begins at its initial value and increments by one on every mutation of the resource; it is the basis for optimistic concurrency control described in §2.9.

A few entities are append-only audit facts and deliberately do **not** carry `updated_at` or `version`; they expose only `id` and `created_at`. These are the privacy-consent records, the trip micro-events, the risk-score snapshots, and the discount-grant legs. For each of those four entity types, neither `updated_at` nor `version` is present, because they are written once and never modified.

The entire platform reads time from a single logical clock rather than wall-clock time, so that test scenarios are deterministic. On server startup the clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly set it stays at that default and never falls back to real time. An `UnderwritingOps` operator advances or resets the clock by supplying an absolute UTC instant in the `to_iso8601` field; the response reports the new `current_utc`. Every deadline, expiry, and window check in the system — scoring deadlines, quote expiry, trip-time ordering, consent effective instants, and snapshot timestamps — reads this clock.

### 2.5. Nested Resource Retrieval and Filtered Discovery

The topology is flat: every entity is its own top-level collection, and parent/child relationships are expressed through foreign-key fields rather than nested URL paths. A child collection is discovered by filtering its top-level list on the relevant foreign key — for example, a policy's trips are found by listing trips filtered by `policy_id`, a driver's consent history by listing that driver's privacy consents, a discount bank's grant legs by listing grants under that bank, and a policy's risk snapshots by listing snapshots for that policy. When a request addresses a resource by an `id` in its path, that `id` must resolve to an existing resource; if it does not, the request is rejected with `ERR_NOT_FOUND`. Where a path contains more than one identifier, the identifiers are validated left-to-right, and the first one that fails to resolve produces the `ERR_NOT_FOUND` rejection before any later identifier or business rule is considered. A request whose body is malformed — missing a required field or carrying a value of the wrong type — is rejected with `ERR_VALIDATION`.

### 2.6. Precision, Rounding, and Monetary Conservation

All money is held in integer cents. Wherever a calculation produces a fractional cent, the result is rounded to a whole cent using the round-half-up method (a value exactly at the half rounds up to the larger magnitude). Risk scores are real numbers rounded to two decimal places, again round-half-up. The multiplier table values are exact two-decimal constants and are not themselves rounded.

Two conservation invariants hold across the system. First, a driver's `lifetime_safe_miles` is a conserved odometer: it only ever increases as accepted policy trips add their distance, and it decreases only through the compensating reversal that occurs when an accepted trip is voided. Second, a driver's discount bank obeys the identity that available funds equal cumulative earned funds minus cumulative redeemed funds, and available funds may never go negative. Both the earned and redeemed totals are monotonic non-decreasing; a reversal of a previously earned safe-trip grant reduces the earned total but is constructed so that available funds remain non-negative.

### 2.7. The Dual-Variant Risk Model

Risk is scored by two sibling calculations that share the same rate-plan weights but differ in normalization, and the difference is deliberate. During the test-drive enrollment the **provisional** variant is forward-looking and normalizes event counts per 100 miles, so that a short test drive is not unfairly penalized merely for accumulating few miles. Once a policy is bound the **operational** variant accumulates event counts in absolute terms over the policy lifetime, so that a driver who drives more carries more exposure. For identical trips these two variants yield different numbers — the provisional score divides by mileage while the operational score does not — and that divergence is intended, not a defect. Both feed the same multiplier table (§2.8) to translate a score into a price multiplier. The precise formulas live in §3 alongside the workflows that trigger them.

### 2.8. Risk Multiplier Tiers

A risk score is converted to a premium multiplier through a fixed four-tier table with half-open boundaries. A score strictly below 10.0 lands in the SAFE tier and yields a multiplier of 0.85. A score of at least 10.0 but strictly below 25.0 lands in the STANDARD tier and yields 1.00. A score of at least 25.0 but strictly below 50.0 lands in the ELEVATED tier and yields 1.25. A score of 50.0 or greater lands in the HIGH tier and yields 1.60. After tier selection, the multiplier is clamped so that it is never below a floor of 0.85 and never above a ceiling of 1.60; because the table values already lie within that band the clamp is a guard rather than an active adjustment. This same multiplier logic is applied at quote generation, on every trip accept and void (to refresh the policy's live multiplier), and at renewal.

### 2.9. Optimistic Concurrency Control

Three write operations require the client to prove it is acting on a current view of a parent resource. Opening a renewal and creating a premium statement both require an `expected_policy_version` field carrying the client's last-observed `version` of the target `Policy`; reopening a claim requires an `expected_claim_version` field carrying the client's last-observed `version` of the target `Claim`. The supplied expected version is checked against the parent's current `version` before any business logic runs. If it does not match — because another writer has advanced the parent's version since the client last read it — the request is rejected with `ERR_STALE_VERSION` at HTTP 412. Each of these rules is detailed in the relevant §3 workflow. Endpoints not named here do not take a version field and perform no concurrency check.

### 2.10. Hierarchical Consistency and Cascades

Several operations mutate more than one resource. When a trip is accepted or voided, the owning policy's live score, live multiplier, and version all change, a new risk-score snapshot is appended, and the driver's discount bank and lifetime miles may move — every one of these secondary effects is part of the single operation and is described with its workflow in §3. When a driver opts out of telematics, the effect cascades to every one of that driver's active policies. Whenever a derived field on a resource changes as a side effect, that resource's `updated_at` is refreshed and its `version` increments accordingly, exactly as for a direct edit.

## 3. Business Logic & Workflows

### 3.1. Rate Plans: the Pricing Configuration

Everything begins with a **rate plan**, the configuration object that an `UnderwritingOps` operator authors to describe how a given US state's policies are priced. A rate plan carries a display `name`, a two-letter `state_code` for the US state it applies to, and a `base_premium_cents` floor — the annual premium baseline in cents, before any telematics adjustment, which must be zero or greater. Mileage billing is governed by two fields: `per_mile_rate_cents`, the cents charged per overage mile (a number — it may be fractional, e.g. 0.5 — that must be zero or greater), and `included_miles_per_period`, the integer number of miles included in each billing period before per-mile charges begin (zero or greater). `base_premium_cents` is likewise required to be a non-negative integer. Risk scoring is driven by three weights the plan supplies: `hard_brake_weight`, `speeding_weight`, and `phone_use_weight`, each applied to the corresponding event count when a score is computed. A freshly created plan has a `status` of `ACTIVE`. An operator may retire a plan, transitioning its `status` to `RETIRED`; a retired plan may no longer back a new quote or a new bind, and an attempt to quote or bind against a retired plan is rejected with `ERR_RATE_PLAN_RETIRED`. Rate plans may be listed (optionally filtered by `state_code`) and fetched individually by any of the three roles.

### 3.2. Drivers, Privacy, and the Opt-Out Cascade

A **driver** is the aggregate root for an insured person and is registered with an `email`, a `full_name`, and a two-letter `state_code` of residence. Email is unique on a case-insensitive basis; registering a second driver with an email that already exists (ignoring case) is rejected with `ERR_DUPLICATE_EMAIL`. Registration may be performed by a `DriverUser` or by `UnderwritingOps`. On creation a driver starts with `status` of `ACTIVE` (the alternative terminal value being `DEACTIVATED`), with `telematics_opted_out` set to false and `lifetime_safe_miles` set to 0, and the system simultaneously provisions a discount bank for the driver.

Privacy is exercised through append-only **privacy-consent** records, each filed by the owning `DriverUser` against their own driver. A consent record carries an `action` of either `GRANT` or `REVOKE`, an optional free-text `reason`, and a system-stamped `effective_at` instant drawn from the logical clock; the record also records the `driver_id` it belongs to. A `REVOKE` is the opt-out: it flips the driver's `telematics_opted_out` from false to true. A `GRANT` is the opt-in: it flips `telematics_opted_out` from true back to false. A consent change that would not alter the current opt-out state is a no-op and is rejected with `ERR_CONSENT_NOOP`; equivalently, a `REVOKE` while the driver is already opted out is rejected with `ERR_ALREADY_OPTED_OUT`, and a `GRANT` while the driver is not opted out is rejected with `ERR_NOT_OPTED_OUT`.

The consequence of opting out reaches beyond the driver record. When a driver revokes consent, every one of that driver's policies whose lifecycle is `ACTIVE` has its telematics dimension transitioned from `CAPTURING` to `SUSPENDED` as a cascade, so that no further trips can be accepted on any of them. When the driver later grants consent again, the reverse cascade returns every active policy's telematics dimension from `SUSPENDED` to `CAPTURING`. A driver's consent history is retrievable as a filtered list.

### 3.3. The Test-Drive Enrollment and Provisional Scoring

Before a price can be offered, a prospective customer runs a scoring period through an **enrollment**. A `DriverUser` opens one by naming the `driver_id` it belongs to, the `rate_plan_id` of the plan being test-driven, and a `scoring_days` window length (an integer constrained to the inclusive range 1 through 90; a value outside that range is rejected with `ERR_VALIDATION`). The system stamps `scoring_started_at` from the logical clock and derives `scoring_deadline` as the start instant plus `scoring_days` days; a freshly opened enrollment has `status` `SCORING` and a `captured_trip_count` of 0 and a `provisional_risk_score` of 0. Trips captured during this window feed the eventual quote. Enrollments may be listed (filtered by `driver_id`, `rate_plan_id`, or `status`) and fetched individually.

While the enrollment is in `SCORING`, the driver attaches scoring trips to it (the trip mechanics are in §3.5). To finalize, the driver finalizes scoring, transitioning the enrollment from `SCORING` to `READY_TO_QUOTE`. Finalization is permitted only when the enrollment is currently in `SCORING` (otherwise `ERR_ENROLLMENT_NOT_SCORING`), when at least three scoring trips have been captured — the minimum scoring-trip count is three — (otherwise `ERR_INSUFFICIENT_SCORING_TRIPS`), and when the logical clock is at or before the `scoring_deadline` (otherwise `ERR_SCORING_WINDOW_EXPIRED`). The act of finalizing recomputes the enrollment's `provisional_risk_score` over its accepted trips using the test-drive variant.

That provisional score is computed as follows. Take only the trips that have been accepted on this enrollment; sum their distances into a total mileage (the minimum-trips rule guarantees this total is positive), and separately sum the hard-brake event counts, the speeding event counts, and the phone-use event counts across those trips. Form a per-100-mile factor equal to 100 divided by the total mileage. Multiply the plan's `hard_brake_weight` by the hard-brake total scaled by that per-100-mile factor, the plan's `speeding_weight` by the speeding total scaled by the same factor, and the plan's `phone_use_weight` by the phone-use total scaled by the same factor; add the three products together and round the sum half-up to two decimal places. Only accepted enrollment trips contribute — open, rejected, and voided trips are excluded.

If a driver wishes to gather more trips after finalizing, reopening scoring reverts the enrollment from `READY_TO_QUOTE` back to `SCORING`. Reopening is permitted only when the enrollment is in `READY_TO_QUOTE` (otherwise `ERR_ENROLLMENT_NOT_READY`) and the clock is still at or before `scoring_deadline` (otherwise `ERR_SCORING_WINDOW_EXPIRED`). After a reopen the driver may capture additional trips, but the `provisional_risk_score` is left stale at its prior value until the next finalize-scoring recomputes it. A driver may abandon an enrollment that is still in `SCORING`, moving it to the terminal `ABANDONED` state; abandonment is allowed only from `SCORING` (otherwise `ERR_ENROLLMENT_NOT_SCORING`). Separately, an `UnderwritingOps` operator may expire a stale enrollment that is still `SCORING` once its window has closed, moving it to the terminal `EXPIRED` state and freezing it so no further trips are accepted; expiry is permitted only when the clock is strictly past `scoring_deadline`, and calling it early is rejected with `ERR_SCORING_WINDOW_NOT_EXPIRED`. The remaining terminal enrollment state, `QUOTED`, is reached when a quote is generated from the enrollment, as described next.

### 3.4. Quotes and Binding into a Policy

An `UnderwritingOps` operator generates a **quote** from a `READY_TO_QUOTE` enrollment by supplying the source `enrollment_id`. The enrollment must be in `READY_TO_QUOTE` for this to succeed; an enrollment that has not been finalized, or one that has already been quoted, is rejected with `ERR_ENROLLMENT_NOT_READY` (a single enrollment cannot back two quotes). On generation the quote records its `driver_id` and copies `rate_plan_id` from the enrollment. It snapshots the enrollment's current `provisional_risk_score` into `locked_risk_score`, which is immutable thereafter. From that locked score it derives `risk_multiplier` via the tier table of §2.8. It then computes `quoted_annual_premium_cents` as the plan's `base_premium_cents` multiplied by that `risk_multiplier`, rounded half-up to the whole cent. The quote's `expires_at` is set to its creation instant plus the quote validity window of fourteen days, and a quote cannot be bound after that instant. A fresh quote has `status` `OPEN`; generating it transitions the source enrollment into its terminal `QUOTED` state. Quotes may be listed (filtered by `driver_id`, `enrollment_id`, `rate_plan_id`, or `status`) and fetched.

An open quote has three exits. The owning `DriverUser` may decline it, moving an `OPEN` quote to the terminal `DECLINED` state (rejected with `ERR_QUOTE_NOT_OPEN` if it is not open). An `UnderwritingOps` operator may expire a quote whose validity window has elapsed, moving it to the terminal `EXPIRED` state; expiry checks only the clock and does not require the quote to be `OPEN` — it is permitted only when the clock is strictly past `expires_at` (an early call is rejected with `ERR_QUOTE_NOT_EXPIRED`), and once that temporal condition holds the quote is moved to `EXPIRED` regardless of its prior status. The third and central exit is binding.

Binding is performed by an `UnderwritingOps` operator who supplies the `quote_id` to create a **policy**. The quote must be `OPEN` (otherwise `ERR_QUOTE_NOT_OPEN`), the clock must be at or before the quote's `expires_at` (otherwise `ERR_QUOTE_EXPIRED`), and the rate plan referenced by the quote must still be `ACTIVE` (otherwise `ERR_RATE_PLAN_RETIRED`). On a successful bind the quote transitions from `OPEN` to the terminal `BOUND` state, and a new policy is created. The policy copies `driver_id` and `rate_plan_id` from the quote, sets `bound_premium_cents` equal to the quote's `quoted_annual_premium_cents` (the contract baseline), and copies the quote's `locked_risk_score` into the policy's `current_risk_score` and the quote's `risk_multiplier` into `current_risk_multiplier`. The new policy opens with `lifecycle_status` `ACTIVE`, `billing_status` `PERIOD_OPEN`, `telematics_status` `CAPTURING`, and `period_index` 0. A first risk-score snapshot is appended at bind with trigger reason `MANUAL`, recording the bound baseline.

### 3.5. Trips and Telematics Events

A **trip** is the append-only fact at the heart of telematics capture, and it belongs to exactly one parent — either a bound policy or a test-drive enrollment, never both and never neither. A `DriverUser` creates a trip by supplying either a `policy_id` or an `enrollment_id` (exactly one of the two), along with a `started_at` instant, an `ended_at` instant, and a `distance_miles` odometer reading. A request body that sets both parents or neither is rejected with `ERR_TRIP_PARENT_AMBIGUOUS`. The `ended_at` instant must be strictly after `started_at`; otherwise the creation is rejected with `ERR_TRIP_TIME_ORDER`. The `distance_miles` must be greater than zero, both at trip creation and at accept time; a non-positive distance is rejected with `ERR_INVALID_TRIP_DISTANCE`. A new trip starts in `status` `OPEN`, with its per-type counters — `hard_brake_count`, `speeding_count`, and `phone_use_count` — initialized to 0, `crash_detected` false, and `billed_period_index` at −1 (meaning not yet pinned to a billing period). Trips may be listed (filtered by `policy_id`, `enrollment_id`, or `status`) and fetched individually.

While a trip is `OPEN`, the driver attaches **trip events** — the braking, speeding, phone-use, and crash micro-events. Each event carries an `event_type` of `HARD_BRAKE`, `SPEEDING`, `PHONE_USE`, or `CRASH`; a `severity` integer from 1 through 5; and an `occurred_at` instant. The event also records the `trip_id` it belongs to. A severity outside the 1-through-5 range, or an `event_type` not in the declared set, is rejected with `ERR_INVALID_EVENT`. The `occurred_at` instant must fall within the half-open interval that starts at the trip's `started_at` (inclusive) and ends at the trip's `ended_at` (exclusive) — that is, at or after the start and strictly before the end; an event outside that interval is rejected with `ERR_EVENT_OUTSIDE_TRIP`. Attaching an event increments the trip's counter for that event type. A `CRASH` event whose `severity` is at least the crash-FNOL severity threshold of 4 sets the trip's `crash_detected` flag to true, arming the FNOL cascade that fires when the trip is accepted. Events may be listed for a trip.

Accepting an `OPEN` trip is the pivotal operation, and it fires a layered cascade. Acceptance requires the trip to be `OPEN` (otherwise `ERR_TRIP_NOT_OPEN`) and the `distance_miles` to still be positive (otherwise `ERR_INVALID_TRIP_DISTANCE`). For a policy-bound trip, the owning policy's telematics dimension must be `CAPTURING` — if it is `SUSPENDED` because the driver opted out, the accept is rejected with `ERR_TELEMATICS_SUSPENDED` — and the policy's billing dimension must be `PERIOD_OPEN`, otherwise `ERR_PERIOD_NOT_OPEN`. For an enrollment-bound trip, the enrollment must be in `SCORING` and the clock at or before its `scoring_deadline`, otherwise `ERR_SCORING_WINDOW_EXPIRED`. When these preconditions hold the trip transitions from `OPEN` to `ACCEPTED` and the cascade runs in order. First, the trip's per-type event counts are frozen from its attached events, and for a policy-bound trip the `billed_period_index` is stamped equal to the owning policy's current `period_index`, pinning which billing period the trip's miles fall into. Next, for an enrollment-bound trip the enrollment's `captured_trip_count` is increased by one; for a policy-bound trip the driver's `lifetime_safe_miles` is increased by the trip's `distance_miles` and the policy's `current_risk_score` is recomputed with the operational variant. Then the policy's `current_risk_multiplier` is recomputed from the new score via the tier table, and a risk-score snapshot is appended with trigger reason `TRIP_ACCEPTED`. Then, if the trip recorded zero hard-brake, zero speeding, and zero phone-use events and its `distance_miles` is at least the safe-trip minimum of 5.0 miles, a safe-trip discount is earned (see below). Finally, if `crash_detected` is true the FNOL claim cascade fires (see §3.8).

The operational risk score for a bound policy is computed over only the accepted trips on that policy, recomputed in full (not incrementally) on each accept and each void. Sum the hard-brake counts, the speeding counts, and the phone-use counts across those accepted trips; multiply the plan's `hard_brake_weight` by the hard-brake total, the plan's `speeding_weight` by the speeding total, and the plan's `phone_use_weight` by the phone-use total; add the three products and round the sum half-up to two decimal places. Unlike the provisional variant, these counts are absolute and are not normalized per 100 miles, so identical trips produce a different number from the provisional score.

The safe-trip discount is a threshold reward. When an accepted policy trip has a hard-brake count of zero **and** a speeding count of zero **and** a phone-use count of zero, and its `distance_miles` is greater than or equal to 5.0 miles, the driver earns a safe-trip discount of 250 cents: the discount bank's `earned_cents` increases by 250 and an earn-leg grant is appended (see §3.10). A trip of exactly 5.0 miles qualifies; any distance below 5.0 does not. If any of the three counts is nonzero, or the distance is below the threshold, nothing is earned.

A `DriverUser` may instead reject an `OPEN` trip, moving it to the terminal `REJECTED` state (rejected with `ERR_TRIP_NOT_OPEN` if it is not open); a rejected trip is excluded from every score and from mileage. An `UnderwritingOps` operator may void an already-`ACCEPTED` trip, moving it to the terminal `VOIDED` state. Voiding requires the trip to be `ACCEPTED` (otherwise `ERR_TRIP_NOT_ACCEPTED`) and requires that no settled statement already covers the trip's billing period (otherwise `ERR_TRIP_PERIOD_SETTLED`). Voiding fires the compensating cascade: for a policy-bound trip the driver's `lifetime_safe_miles` is decreased by the trip's `distance_miles`, restoring the conserved-odometer invariant; the policy's `current_risk_score` is recomputed over the remaining accepted trips with the operational variant (and the multiplier refreshed), and a snapshot is appended with trigger reason `TRIP_VOIDED`; and if this trip had earned a safe-trip grant, the discount bank's `earned_cents` is decreased by 250 and a reversal-leg grant is appended, preserving the non-negative available-funds invariant.

### 3.6. Mileage-Based Premium Statements

Billing runs as a repeating three-phase cycle on the policy's billing dimension: `PERIOD_OPEN` to `PERIOD_CLOSING` to `PERIOD_SETTLED` and back to `PERIOD_OPEN`. An `UnderwritingOps` operator opens a billing period's accounting by creating a **premium statement** for a policy. This requires the policy's `lifecycle_status` to be `ACTIVE` (otherwise `ERR_POLICY_NOT_ACTIVE`) and its `billing_status` to be `PERIOD_OPEN` (otherwise `ERR_PERIOD_NOT_OPEN`), and it requires that no `OPEN` trips remain in the current period window — every trip in the period must already be accepted or rejected — otherwise the creation is rejected with `ERR_OPEN_TRIPS_IN_PERIOD`. The statement-creation request also carries `policy_id` and an `expected_policy_version` that must match the policy's current `version`; if a concurrent writer has accepted or voided a trip (advancing the policy version and changing the multiplier), the snapshot inputs are stale and the create is rejected with `ERR_STALE_VERSION` at HTTP 412. Creating the statement transitions the policy's billing dimension from `PERIOD_OPEN` to `PERIOD_CLOSING` and increments the policy's `version`. The statement is created in `status` `DRAFT` and records its `policy_id` and the `period_index` it covers.

At creation the statement's mileage charges are computed, and the rounding order is pinned. First, `billed_miles` is the sum of `distance_miles` over the accepted policy trips whose `billed_period_index` equals the policy's current `period_index` — the period pin stamped at accept time, which removes any clock-window ambiguity. Then `overage_miles` is the greater of zero and `billed_miles` minus the plan's `included_miles_per_period`. The base charge is the per-period share of the annual contract premium scaled by the live multiplier: take the policy's `bound_premium_cents` divided by the periods-per-year constant of 12, multiply by the policy's `current_risk_multiplier`, and round that single component half-up to a whole cent to obtain `base_charge_cents`. The mileage charge is `overage_miles` multiplied by the plan's `per_mile_rate_cents`, rounded half-up to a whole cent on its own to obtain `mileage_charge_cents`. The two components are rounded **independently first and only then summed** — this round-per-component-then-sum order is deliberate and differs from summing the raw amounts before a single rounding whenever both components carry fractional cents. The pre-discount total of the statement is `base_charge_cents` plus `mileage_charge_cents`. At this draft stage `applied_discount_cents` stands at its default of 0.

A `DRAFT` statement is issued by an `UnderwritingOps` operator, moving its `status` from `DRAFT` to `ISSUED` so that it can be settled; issuing a statement that is not in `DRAFT` is rejected with the generic `ERR_INVALID_STATE`. Statements may be listed (filtered by `policy_id`, `period_index`, or `status`) and fetched.

Settlement is the second phase. An `UnderwritingOps` operator settles an `ISSUED` statement, which transitions the policy's billing dimension from `PERIOD_CLOSING` to `PERIOD_SETTLED`. Settlement requires the policy `lifecycle_status` to be `ACTIVE` (otherwise `ERR_POLICY_NOT_ACTIVE`), the `billing_status` to be `PERIOD_CLOSING` (otherwise `ERR_PERIOD_NOT_CLOSING`), and the statement to be in `ISSUED` (otherwise `ERR_STATEMENT_NOT_ISSUED`). At settlement the discount draw is computed against an apparent circular dependency, resolved by a pinned evaluation order. The pre-discount total — `base_charge_cents` plus `mileage_charge_cents`, already fixed at draft — is taken first. The applied discount is then the lesser of the discount bank's `available_cents` and that pre-discount total, so the bill can never be discounted below zero; this value becomes `applied_discount_cents`. The `total_due_cents` is the pre-discount total minus `applied_discount_cents`, which is non-negative by construction. The discount that is drawn may not exceed either the bank's `available_cents` or the statement's pre-discount total; a draw that would violate either bound is rejected with `ERR_DISCOUNT_OVERDRAW`. On settlement the statement moves to `SETTLED`, the discount bank's `redeemed_cents` increases by `applied_discount_cents`, and a redeem-leg grant is appended. The remaining terminal statement value is `VOIDED`.

The third phase advances the cycle. An `UnderwritingOps` operator advances the period, transitioning the policy's billing dimension from `PERIOD_SETTLED` back to `PERIOD_OPEN`; this requires `lifecycle_status` `ACTIVE` (otherwise `ERR_POLICY_NOT_ACTIVE`) and `billing_status` `PERIOD_SETTLED` (otherwise `ERR_PERIOD_NOT_SETTLED`). Advancing increases the policy's `period_index` by one and opens a fresh period window.

### 3.7. Policy Lifecycle Termination

The policy's lifecycle dimension gates both the billing and telematics dimensions. From `ACTIVE` a policy may move to one of two terminal lifecycle states. An `UnderwritingOps` operator may lapse an `ACTIVE` policy, transitioning `lifecycle_status` to `LAPSED`; lapsing is blocked if a statement is in `ISSUED` status awaiting settlement, in which case it is rejected with `ERR_UNSETTLED_STATEMENT`. An operator may instead cancel an `ACTIVE` policy, transitioning `lifecycle_status` to `CANCELLED`; cancellation is blocked while any claim on the policy is in `FNOL`, `UNDER_REVIEW`, or `REOPENED` status, in which case it is rejected with `ERR_OPEN_CLAIM_BLOCKS_CANCEL`. Both transitions require the policy to currently be `ACTIVE`, otherwise `ERR_POLICY_NOT_ACTIVE`. On either lapse or cancel, the telematics dimension is moved to `SUSPENDED` and the billing dimension is frozen. Policies may be listed (filtered by `driver_id`, `quote_id`, `rate_plan_id`, or `lifecycle_status`) and fetched, the fetch exposing all three status dimensions together with the live computed scores.

### 3.8. Crash Detection and the FNOL Claim Lifecycle

When a policy-bound trip carrying a qualifying crash is accepted, the platform automatically opens a **claim** as a First Notice Of Loss — this auto-FNOL is mandatory and cannot be suppressed; an internal guard rejects any path where a crash trip is accepted without firing FNOL via `ERR_CRASH_FNOL_REQUIRED`. An auto-created claim records the `policy_id`, the `trip_id` of the crash trip, an `origin` of `AUTO_FNOL`, and a `reported_severity` copied from the triggering `CRASH` event; it opens in `status` `FNOL` with `reserve_cents` 0 and `reopen_count` 0. Separately, a `DriverUser` or a `ClaimsAdjuster` may file a manual claim by supplying the `policy_id`, a `reported_severity`, and an optional `reason`; a manual claim has `origin` `MANUAL`, takes its `reported_severity` from the input (an integer constrained to the inclusive range 1 through 5; a value outside that range is rejected with `ERR_VALIDATION`), has no `trip_id`, and likewise opens in `FNOL`. Claims may be listed (filtered by `policy_id`, `trip_id`, `status`, or `origin`) and fetched.

A `ClaimsAdjuster` drives the claim through its lifecycle. Triage moves a claim from `FNOL` to `UNDER_REVIEW`; it requires the claim to be in `FNOL` (otherwise `ERR_CLAIM_NOT_FNOL`) and the owning policy's `lifecycle_status` to be `ACTIVE` (otherwise `ERR_POLICY_NOT_ACTIVE`). Triage sets the loss reserve: `reserve_cents` is the reserve base of 100000 cents multiplied by the claim's `reported_severity`. The triage request may carry an optional `reserve_severity_override`, but this field is accepted and ignored — the reserve is always derived from the claim's stored `reported_severity` and the override does not alter it. Closing moves a claim from `UNDER_REVIEW` to `CLOSED`, releasing the reserve; the same close action also serves a `REOPENED` claim (moving it to `CLOSED`), and a close attempted on a claim that is in neither `UNDER_REVIEW` nor `REOPENED` is rejected with `ERR_CLAIM_NOT_UNDER_REVIEW`.

A closed claim may cycle. A `ClaimsAdjuster` may reopen a `CLOSED` claim, moving it to `REOPENED`; reopening requires the claim to be `CLOSED` (otherwise `ERR_CLAIM_NOT_CLOSED`), requires that the `reopen_count` is strictly less than the maximum of two reopens (otherwise `ERR_REOPEN_LIMIT_REACHED`), and requires an `expected_claim_version` that matches the claim's current `version` (otherwise `ERR_STALE_VERSION` at HTTP 412). A successful reopen increases `reopen_count` by one, restores the reserve (recomputed as the reserve base of 100000 cents multiplied by the claim's `reported_severity`, identically to triage), returns the claim to active handling, and increments the claim's `version`. A `REOPENED` claim is closed again through the same close action (a close on any state other than `UNDER_REVIEW` or `REOPENED` yields `ERR_CLAIM_NOT_UNDER_REVIEW`, so the catalogued `ERR_CLAIM_NOT_REOPENABLE` is not surfaced by this implementation); when the claim is closed and its `reopen_count` has reached the maximum of two, that `CLOSED` state is terminal.

### 3.9. Renewal Recalculation

At the end of a term, an `UnderwritingOps` operator opens a **renewal** to reprice the policy. Opening a renewal supplies the `policy_id` and an `expected_policy_version` that must match the policy's current `version`; if another writer has since accepted a prior renewal or settled a statement (legitimately advancing the baseline), the current writer's view is stale and the open is rejected with `ERR_STALE_VERSION` at HTTP 412. Opening also increments the policy's `version`. The renewal records `prior_premium_cents` as the policy's `bound_premium_cents` at the moment it opened, snapshots the policy's `current_risk_score` into `recalculated_risk_score`, and derives a renewal multiplier from that score via the tier table. From there it computes `recalculated_premium_cents` as the plan's `base_premium_cents` multiplied by the renewal multiplier, rounded half-up to the whole cent. It also computes `banked_discount_applied_cents` as the lesser of the discount bank's `available_cents` and the renewal discount cap of 50000 cents. A new renewal opens in `status` `PROPOSED`. Renewals may be listed (filtered by `policy_id` or `status`) and fetched.

An operator either accepts or declines a proposed renewal. Accepting requires the renewal to be `PROPOSED` (otherwise `ERR_RENEWAL_NOT_PROPOSED`), the policy `lifecycle_status` to be `ACTIVE` (otherwise `ERR_POLICY_NOT_ACTIVE`), and an `expected_policy_version` matching the policy's current `version` (otherwise `ERR_STALE_VERSION` at HTTP 412). On accept the policy's `bound_premium_cents` is reset to `recalculated_premium_cents` minus `banked_discount_applied_cents`, the discount bank's `redeemed_cents` increases by `banked_discount_applied_cents`, a redeem-leg grant is appended, and the policy's `version` increments; the renewal moves to the terminal `ACCEPTED` state. The discount swept at accept may not exceed the bank's `available_cents`; a sweep that would overdraw the bank is rejected with `ERR_DISCOUNT_OVERDRAW`. Declining a `PROPOSED` renewal (otherwise `ERR_RENEWAL_NOT_PROPOSED`) discards it into the terminal `DECLINED` state and leaves the policy's premium unchanged.

### 3.10. The Discount Bank and Its Grant Ledger

Each driver owns exactly one **discount bank**, provisioned automatically at registration, which tracks the driver's safe-driving savings. It records the owning `driver_id`, a monotonic non-decreasing `earned_cents` total of all discount earned from safe-driving grants, a monotonic non-decreasing `redeemed_cents` total consumed by statement settlements and renewals, and an `available_cents` figure equal to `earned_cents` minus `redeemed_cents` that is invariantly never negative. Banks may be listed (filtered by `driver_id`, with one bank per driver) and fetched.

Every movement of the bank is recorded as an append-only **discount grant** leg. A grant records the `discount_bank_id` it belongs to, a `leg` of `EARN`, `REDEEM`, or `REVERSAL`, an `amount_cents` positive magnitude, a `source_reason`, and a system-stamped `granted_at` instant from the logical clock. The earn legs arise from safe trips and carry `source_reason` `SAFE_TRIP`. Redeem legs arise from statement settlement (with `source_reason` `STATEMENT_REDEEM`) and from renewal acceptance (with `source_reason` `RENEWAL_REDEEM`). Reversal legs arise when an accepted safe trip is voided, carrying `source_reason` `TRIP_VOID_REVERSAL` and unwinding a previously earned safe-trip grant. A bank's grant legs are retrievable as a filtered list.

### 3.11. Risk-Score Snapshots

Each bound policy accumulates an append-only history of **risk-score snapshots** for audit and traceability. A snapshot records the `policy_id`, a `trigger_reason` of `TRIP_ACCEPTED`, `TRIP_VOIDED`, `RENEWAL`, or `MANUAL`, the operational `risk_score` value at snapshot time, the `risk_multiplier` value at snapshot time, and a `snapshot_at` instant from the logical clock. A snapshot is appended when a policy is first bound (with reason `MANUAL`), on every trip accept (`TRIP_ACCEPTED`), and on every trip void (`TRIP_VOIDED`). A policy's snapshots are retrievable as a filtered list.

### 3.12. Ordering of Validation Checks

Where several validations could apply to one request, they are evaluated in a fixed precedence so that the right error surfaces. Authentication comes first: a missing or malformed user context (`ERR_MISSING_USER_CONTEXT`, 401) is caught before anything else, then role permission (`ERR_FORBIDDEN_ROLE`, 403), then resource ownership for a `DriverUser` acting on a driver-scoped resource (`ERR_NOT_RESOURCE_OWNER`, 403). Existence is checked next: every path identifier must resolve, left-to-right, or `ERR_NOT_FOUND` (404) is returned. Then, where applicable, the optimistic-concurrency version check runs (`ERR_STALE_VERSION`, 412) before any business logic. Only then are state-transition preconditions evaluated — a resource not in the required state for its requested transition yields the domain-specific state error for that transition (the generic form being `ERR_INVALID_STATE`, 409) — followed by the referential, safety, temporal, constraint, and fiscal business rules described throughout this section. This ordering ensures, for example, that a stale-version rejection is not masked by a later state check, and that an existence failure is reported before a permission-scoped owner check on a resource that does not exist.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including state transitions and the logical-clock set — return `200 OK`. The complete request and response shape for each endpoint must be reconstructed from the workflow narratives in Section 3; the table below lists only the method, path, purpose, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock to an absolute UTC instant | UnderwritingOps |
| POST | `/rate-plans` | Create a rate plan | UnderwritingOps |
| GET | `/rate-plans` | List rate plans (filter by state_code) | UnderwritingOps, DriverUser, ClaimsAdjuster |
| GET | `/rate-plans/{id}` | Get a rate plan | UnderwritingOps, DriverUser, ClaimsAdjuster |
| POST | `/rate-plans/{id}/retire` | Retire a rate plan | UnderwritingOps |
| POST | `/drivers` | Register a driver | DriverUser, UnderwritingOps |
| GET | `/drivers` | List drivers (filter by email) | UnderwritingOps, ClaimsAdjuster |
| GET | `/drivers/{id}` | Get a driver | DriverUser, UnderwritingOps, ClaimsAdjuster |
| POST | `/drivers/{id}/privacy-consents` | Record a consent change (opt-out/opt-in) | DriverUser |
| GET | `/drivers/{id}/privacy-consents` | List a driver's consent events | DriverUser, UnderwritingOps |
| GET | `/discount-banks` | List discount banks (filter by driver_id) | DriverUser, UnderwritingOps |
| GET | `/discount-banks/{id}` | Get a discount bank | DriverUser, UnderwritingOps |
| GET | `/discount-banks/{id}/grants` | List grant legs | DriverUser, UnderwritingOps |
| POST | `/enrollments` | Open a test-drive scoring enrollment | DriverUser |
| GET | `/enrollments` | List enrollments (filter by driver_id, rate_plan_id, status) | DriverUser, UnderwritingOps |
| GET | `/enrollments/{id}` | Get an enrollment | DriverUser, UnderwritingOps |
| POST | `/enrollments/{id}/finalize-scoring` | Finalize scoring and compute the provisional score | DriverUser |
| POST | `/enrollments/{id}/reopen-scoring` | Reopen scoring to capture more trips | DriverUser |
| POST | `/enrollments/{id}/abandon` | Abandon a scoring enrollment | DriverUser |
| POST | `/enrollments/{id}/expire` | Expire a scoring enrollment past its deadline | UnderwritingOps |
| POST | `/quotes` | Generate a quote from a ready enrollment | UnderwritingOps |
| GET | `/quotes` | List quotes (filter by driver_id, enrollment_id, rate_plan_id, status) | DriverUser, UnderwritingOps |
| GET | `/quotes/{id}` | Get a quote | DriverUser, UnderwritingOps |
| POST | `/quotes/{id}/decline` | Decline an open quote | DriverUser |
| POST | `/quotes/{id}/expire` | Expire an open quote past its validity | UnderwritingOps |
| POST | `/policies` | Bind an open, unexpired quote into a policy | UnderwritingOps |
| GET | `/policies` | List policies (filter by driver_id, quote_id, rate_plan_id, lifecycle_status) | DriverUser, UnderwritingOps, ClaimsAdjuster |
| GET | `/policies/{id}` | Get a policy | DriverUser, UnderwritingOps, ClaimsAdjuster |
| POST | `/policies/{id}/lapse` | Lapse an active policy | UnderwritingOps |
| POST | `/policies/{id}/cancel` | Cancel an active policy | UnderwritingOps |
| POST | `/policies/{id}/advance-period` | Advance the billing period | UnderwritingOps |
| GET | `/policies/{id}/risk-snapshots` | List a policy's risk-score snapshots | DriverUser, UnderwritingOps |
| POST | `/trips` | Create an open trip on a policy or enrollment | DriverUser |
| GET | `/trips` | List trips (filter by policy_id, enrollment_id, status) | DriverUser, UnderwritingOps |
| GET | `/trips/{id}` | Get a trip | DriverUser, UnderwritingOps, ClaimsAdjuster |
| POST | `/trips/{id}/events` | Attach a telematics micro-event to an open trip | DriverUser |
| GET | `/trips/{id}/events` | List a trip's events | DriverUser, UnderwritingOps, ClaimsAdjuster |
| POST | `/trips/{id}/accept` | Accept an open trip and fire the cascade | DriverUser |
| POST | `/trips/{id}/reject` | Reject an open trip | DriverUser |
| POST | `/trips/{id}/void` | Void an accepted trip with compensation | UnderwritingOps |
| POST | `/statements` | Create a draft statement for the current period | UnderwritingOps |
| GET | `/statements` | List statements (filter by policy_id, period_index, status) | DriverUser, UnderwritingOps |
| GET | `/statements/{id}` | Get a statement | DriverUser, UnderwritingOps |
| POST | `/statements/{id}/issue` | Issue a draft statement | UnderwritingOps |
| POST | `/statements/{id}/settle` | Settle an issued statement and draw discount | UnderwritingOps |
| POST | `/renewals` | Open a renewal recalculation for a policy | UnderwritingOps |
| GET | `/renewals` | List renewals (filter by policy_id, status) | DriverUser, UnderwritingOps |
| GET | `/renewals/{id}` | Get a renewal | DriverUser, UnderwritingOps |
| POST | `/renewals/{id}/accept` | Accept a proposed renewal | UnderwritingOps |
| POST | `/renewals/{id}/decline` | Decline a proposed renewal | UnderwritingOps |
| POST | `/claims` | File a manual claim against a policy | DriverUser, ClaimsAdjuster |
| GET | `/claims` | List claims (filter by policy_id, trip_id, status, origin) | DriverUser, UnderwritingOps, ClaimsAdjuster |
| GET | `/claims/{id}` | Get a claim | DriverUser, UnderwritingOps, ClaimsAdjuster |
| POST | `/claims/{id}/triage` | Triage a claim and set its reserve | ClaimsAdjuster |
| POST | `/claims/{id}/close` | Close a claim | ClaimsAdjuster |
| POST | `/claims/{id}/reopen` | Reopen a closed claim | ClaimsAdjuster |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_RATE_PLAN_RETIRED` | 409 |
| `ERR_ENROLLMENT_NOT_SCORING` | 409 |
| `ERR_ENROLLMENT_NOT_READY` | 409 |
| `ERR_INSUFFICIENT_SCORING_TRIPS` | 422 |
| `ERR_SCORING_WINDOW_EXPIRED` | 409 |
| `ERR_SCORING_WINDOW_NOT_EXPIRED` | 409 |
| `ERR_QUOTE_NOT_OPEN` | 409 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_QUOTE_NOT_EXPIRED` | 409 |
| `ERR_POLICY_NOT_ACTIVE` | 409 |
| `ERR_PERIOD_NOT_OPEN` | 409 |
| `ERR_PERIOD_NOT_CLOSING` | 409 |
| `ERR_PERIOD_NOT_SETTLED` | 409 |
| `ERR_OPEN_TRIPS_IN_PERIOD` | 409 |
| `ERR_UNSETTLED_STATEMENT` | 409 |
| `ERR_OPEN_CLAIM_BLOCKS_CANCEL` | 409 |
| `ERR_TRIP_PARENT_AMBIGUOUS` | 422 |
| `ERR_TRIP_NOT_OPEN` | 409 |
| `ERR_TRIP_NOT_ACCEPTED` | 409 |
| `ERR_TELEMATICS_SUSPENDED` | 409 |
| `ERR_CRASH_FNOL_REQUIRED` | 409 |
| `ERR_TRIP_TIME_ORDER` | 422 |
| `ERR_EVENT_OUTSIDE_TRIP` | 422 |
| `ERR_INVALID_TRIP_DISTANCE` | 422 |
| `ERR_INVALID_EVENT` | 422 |
| `ERR_TRIP_PERIOD_SETTLED` | 409 |
| `ERR_STATEMENT_NOT_ISSUED` | 409 |
| `ERR_DISCOUNT_OVERDRAW` | 409 |
| `ERR_RENEWAL_NOT_PROPOSED` | 409 |
| `ERR_CLAIM_NOT_FNOL` | 409 |
| `ERR_CLAIM_NOT_UNDER_REVIEW` | 409 |
| `ERR_CLAIM_NOT_CLOSED` | 409 |
| `ERR_CLAIM_NOT_REOPENABLE` | 409 |
| `ERR_REOPEN_LIMIT_REACHED` | 409 |
| `ERR_ALREADY_OPTED_OUT` | 409 |
| `ERR_NOT_OPTED_OUT` | 409 |
| `ERR_CONSENT_NOOP` | 409 |
| `ERR_VALIDATION` | 422 |
| `ERR_DUPLICATE_EMAIL` | 409 |
