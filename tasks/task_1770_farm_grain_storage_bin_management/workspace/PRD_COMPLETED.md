# Farm Grain Bin Management API — Product Requirements Document

## 1. Introduction

Every harvest, an on-farm grain operation faces the same compounding gamble: bushels sitting in bins quietly lose weight to moisture shrink and invisible handling loss, a single undetected hotspot can destroy tens of thousands of bushels before anyone smells smoke, and a marketing contract signed in July has to be physically delivered out of those same bins during a fixed winter window — all while fumigation lockouts, confined-space entry rules, and insurance documentation obligations constrain when grain can be touched at all. The operations that win this gamble are the ones that measure relentlessly, act on thresholds rather than hunches, and keep their books reconciled to the last tenth of a bushel.

This document specifies the Farm Grain Bin Management API, the system of record for that operation. It governs bin inventory by crop, grade, and fill date; temperature-cable monitoring with automated spoilage-risk scoring and hotspot alerting; insect-control fumigation records with legally mandated restricted-entry intervals and segregation of duties; bin-entry safety permits; load-out scheduling against marketing contracts through dispatch, scale-ticket delivery, and money settlement; a monthly assessment epoch that posts storage charges and invisible loss while sweeping expired obligations; insurance policies and spoilage claims; and a forward-looking carry analysis that tells the operator, for any lot, whether holding the grain one more month earns more than it costs. All temporal rules in the system are evaluated against a server-side logical clock rather than wall-clock time, so that every deadline, interval, and expiry is deterministic and testable.

The API is consumed by four acting roles — the site manager who runs the physical operation, the farm owner who owns the money side, the certified applicator who fumigates, and the safety officer who authorizes bin entry — and every rule below is written so that a reader can implement the system from this document alone.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, conventions, and cross-cutting rules that apply to every endpoint and every entity.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The system recognizes exactly four role values: `SiteManager`, `FarmOwner`, `CertifiedApplicator`, and `SafetyOfficer`. A request missing either header — an empty value counts as missing — or presenting a role value outside that set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A well-formed request whose role is not permitted to invoke the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The four roles divide the operation deliberately. A `SiteManager` runs the bin site: creating bins and lots, ingesting temperature readings, closing spoilage alerts, scheduling and settling load-outs, submitting insurance claims, registering applicators, running monthly assessments, and driving the logical clock. A `FarmOwner` controls the money side: creating marketing contracts and insurance policies and approving insurance claims. A `CertifiedApplicator` creates and clears fumigation records. A `SafetyOfficer` approves bin-entry permits. Read access is broad: every GET endpoint in the system accepts any of the four roles. Entry-permit creation is shared between `SiteManager` and `SafetyOfficer`, and the carry-analysis capability is shared between `SiteManager` and `FarmOwner`.

The meaning of `X-User-ID` differs by role, and the distinction is load-bearing. When `X-User-Role` is `CertifiedApplicator`, `X-User-ID` is the `id` of the acting `Applicator` entity; ownership checks on any resource that references an applicator — in particular the `applicator_id` of a fumigation record — compare that foreign-key field to `X-User-ID`. When `X-User-Role` is `SiteManager`, `FarmOwner`, or `SafetyOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `requester_user_id` or `approver_user_id` on a bin-entry permit) but never compares it to any entity's `id`. Segregation-of-duties rules compare these recorded identifiers: the applicator who clears a fumigation must not be the applicator who applied it, and the safety officer who approves a permit must not be the user who requested it.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock of §2.4 rather than wall-clock time.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format — including requests that match no route and requests using an unsupported method on a known route, which are answered with `ERR_NOT_FOUND` (HTTP 404):

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1 to 100, or a negative `offset` is rejected with `ERR_VALIDATION` (HTTP 400).

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties on `created_at` broken by the order in which the server accepted the records. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope. An enum-typed filter value outside the field's allowed set is rejected with `ERR_VALIDATION` (HTTP 400); identifier filters match on equality only, so a filter naming a nonexistent identifier yields an empty page rather than an error.

### 2.4. The Logical Clock

All time-sensitive evaluation in the system — restricted-entry intervals, delivery windows, permit and policy expiries, the monthly assessment epoch — is keyed on a server-side **logical clock**, never on wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and the server never falls back to wall-clock time under any circumstance.

A test-driving capability, restricted to `SiteManager`, advances the logical clock to a caller-supplied `to_iso8601` instant — which may be earlier or later than the current value, with no monotonicity constraint — and returns the resulting `current_utc`; a missing or unparseable `to_iso8601` is rejected with `ERR_VALIDATION` (HTTP 400). Wherever this document says "now", it means the logical clock.

### 2.5. Common Resource Properties

Most resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` timestamps are ISO 8601 UTC values with three fractional digits stamped from the logical clock; `updated_at` refreshes on every mutation of the resource. The same serialization — ISO 8601 UTC with exactly three fractional digits and a `Z` suffix — applies to every other timestamp the server emits, whether a client-supplied instant echoed back (such as `fill_date`, `recorded_at`, `cert_expires_at`, `application_start`, `application_end`, or window, planned, scheduled, and coverage bounds) or a server-derived instant (such as `lockout_until`, `cleared_at`, `closed_at`, `delivered_at`, `last_reading_at`, and the clock endpoint's `current_utc`). Client-supplied timestamps may carry any ISO 8601 offset and are normalized to UTC; a timestamp with no offset is read as UTC. The `version` is a system-managed integer that starts at 1 at creation and increments by one on every mutation, including mutations driven by cascades rather than direct client writes.

Three record types are immutable event logs and carry only `id` and `created_at`: temperature readings, storage assessments, and shrink events. Both `updated_at` and `version` are absent from these three resources — they are written once and never modified.

### 2.6. Numeric Precision and Rounding

Bushel quantities — fills, draws, shrink amounts, lot balances, bin inventories, contract commitments — are stored and compared at exactly 2 decimal places, rounded half up. Moisture percentage and temperature inputs are taken at 1 decimal place; per-cable temperature entries carry no range restriction. The bin spoilage risk score is computed and stored at 2 decimal places, rounded half up. All monetary values are integer cents, rounded half up; per-bushel prices, basis values, and bonuses are integer cents inputs. A claim's per-bushel unit valuation is carried at 2 decimal places, and a contract's fulfillment ratio is carried at 4 decimal places, rounded half up. Quantities, scores, and ratios serialize as JSON numbers; monetary cent amounts serialize as JSON integers.

Threshold comparisons throughout the system are exact and inclusive where stated: a comparison phrased as "at least" admits the boundary value itself.

### 2.7. Bin Posture: The Derived Safety Gate

Every bin carries a stored, derived field `posture` taking one of four values: `SOUND`, `WATCH`, `ALERT`, or `FUMIGATION_LOCKOUT`. Posture is not set directly by any client; the server recomputes it whenever its inputs change, and it gates the physical operations of the site.

Recomputation follows a strict ladder, evaluated in this order. First, if any fumigation record on the bin is `ACTIVE` with an `application_start` at or before now, the posture is `FUMIGATION_LOCKOUT`. Otherwise, if any spoilage alert on the bin is `OPEN`, the posture is `ALERT`. Otherwise, if the bin's current `risk_score` is at least 70.00, the posture is `ALERT` — a score of exactly 70.00 alerts. Otherwise, if the `risk_score` is at least 40.00, the posture is `WATCH` — a score of exactly 40.00 watches. Otherwise the posture is `SOUND`. The triggers that fire a recompute are: ingestion of a temperature reading, closure of a spoilage alert, creation or clearance of a fumigation, creation of a lot, confirmation or voiding of a settlement, and the monthly assessment epoch.

Posture changes cascade. Entering `ALERT` or `FUMIGATION_LOCKOUT` from `SOUND` or `WATCH` fires the **gate cascade**: every lot of the bin in `STORED` or `PARTIALLY_DRAWN` status moves to `SUSPENDED`; every load-out of the bin in `SCHEDULED` transport status moves to `HELD` with `held_reason` set to `POSTURE`, and each held load-out reduces its contract's `committed_bu` by its `planned_bu` and increments the contract's `version`; additionally, when the destination is `FUMIGATION_LOCKOUT`, every entry permit of the bin in `REQUESTED` or `APPROVED` status moves to `VOIDED`. Entering `SOUND` or `WATCH` from `ALERT` or `FUMIGATION_LOCKOUT` fires the **release cascade**: suspended lots return to `STORED` if their `drawn_bu` is zero and to `PARTIALLY_DRAWN` otherwise; held load-outs return to `SCHEDULED` with `held_reason` cleared to null, each restoring its `planned_bu` to the contract's `committed_bu` and incrementing the contract's `version`. Entering `FUMIGATION_LOCKOUT` from `ALERT` still voids the bin's `REQUESTED` and `APPROVED` entry permits, while its lots and load-outs are already gated and simply remain so. Moving from `FUMIGATION_LOCKOUT` to `ALERT` performs no release at all: lots stay `SUSPENDED` and load-outs stay `HELD`. A recompute that leaves a bin inside the `WATCH` band — a self-transition from `WATCH` to `WATCH` — updates the `risk_score` field only and fires no cascade of any kind.

Three operations are gated on posture: filling a new lot, scheduling a load-out, and dispatching a scheduled load-out each require the bin's posture to be `SOUND` or `WATCH`. Against a bin in `ALERT` or `FUMIGATION_LOCKOUT`, any of the three is rejected with `ERR_BIN_POSTURE_BLOCKED` (HTTP 409).

### 2.8. Optimistic Concurrency Control

Exactly one write in the system is protected by optimistic concurrency control: scheduling a load-out against a marketing contract. The scheduling request must carry `expected_contract_version`, a non-optional field holding the `version` of the target contract as the client last observed it. If that value does not match the contract's current `version` at the moment the write is evaluated — because the contract has been mutated since the client read it, whether by another load-out committing bushels, a settlement posting or reversing, a posture hold or release, or an assessment sweep — the request is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412) and no load-out is created; the client must re-read the contract before re-planning. A non-integer `expected_contract_version` is a shape defect reported as `ERR_VALIDATION` (HTTP 400); the stale-version comparison applies only to integer values. No other endpoint accepts or requires a version field.

### 2.9. Resource Lookup and Validation Precedence

The resource graph is flat: entities are peers joined by foreign-key fields in request bodies, not by nested URL ownership. When a request must resolve identifiers, the server validates path identifiers first, from left to right, and then foreign-key identifiers in the request body in the order the endpoint's narrative names them; the first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND` (HTTP 404). A foreign-key field that is absent or null is not an identifier at all but a shape defect, reported as `ERR_VALIDATION` from the shape layer below.

On any endpoint that enforces several rules, failures surface in a fixed precedence order so that the earliest applicable rejection is always the one returned. The layers, from earliest to latest, are: authentication and role authorization, including the fumigation rule that the acting applicator acts as their own record; then resource existence; then the optimistic-concurrency check on contract version; then request-shape validation (`ERR_VALIDATION`, HTTP 400) covering a request body that is not a JSON object, required fields, enum membership, numeric ranges, date ordering, conditional fields, and ticket-number uniqueness; then segregation-of-duties rejections; then state-machine preconditions; then posture and safety checks; then temporal and window rules; then capacity, crop-consistency, and uniqueness constraints; then referential-state requirements on related resources; and finally fiscal coverage checks. A request-shape defect therefore masks every later rule — a malformed payload is always answered with `ERR_VALIDATION` before any state or business check runs — and a segregation-of-duties rejection precedes the state checks of the same endpoint. The workflow sections below name the concrete per-endpoint chains inside this global order.

## 3. Business Logic & Workflows

### 3.1. Establishing the Site: Bins, Applicators, and Grain Lots

A `SiteManager` brings a bin under management by supplying a `name` (a label such as BIN-N1), a `capacity_bu` giving the maximum bushels the bin can physically hold — a 2-decimal value strictly greater than zero — and a `crop` designation of `CORN`, `SOYBEAN`, or `WHEAT`. A new bin starts clean: `posture` is `SOUND`, `risk_score` is 0.00, `current_inventory_bu` is 0.00, `insect_activity` is false, and `last_reading_at` is null. The `current_inventory_bu` of a bin is at all times the sum of `current_bu` over every lot assigned to that bin, recomputed whenever lot inventory moves; the bin's `insect_activity` and `last_reading_at` mirror the bin's latest temperature reading, and `risk_score` mirrors the score computed from that reading, staying at 0 while no readings exist.

Fumigation is performed by licensed professionals, so before any fumigation can be recorded a `SiteManager` registers each applicator with a `name`, a state-issued `license_no`, and a `cert_expires_at` certification expiry. The registered `Applicator` record is what a `CertifiedApplicator` caller authenticates as later.

Filling a bin creates a grain lot. A `SiteManager` submits the receiving `bin_id`; the `crop` (`CORN`, `SOYBEAN`, or `WHEAT`); the USDA quality `grade` (`GRADE_1`, `GRADE_2`, or `GRADE_3`); the `fill_date` recording when the grain was binned; the `original_bu` gross bushels (2 decimal places, strictly greater than zero); the `fill_moisture_pct` moisture at fill (1 decimal place, between 0 and 40 inclusive); the local `fill_basis_cents` in cents per bushel against futures, which may be negative; and a `reference_price_cents_per_bu` flat-price reference in cents per bushel, strictly greater than zero, which the carry analysis later uses as the grain's financing base. The guards fire in the global precedence order: the named bin must exist (otherwise `ERR_NOT_FOUND`); the payload must be well-formed, so a missing field or an out-of-range moisture surfaces as `ERR_VALIDATION`; the bin's posture must be `SOUND` or `WATCH` (otherwise `ERR_BIN_POSTURE_BLOCKED`); the fill must fit — the sum of `current_bu` over the bin's existing lots plus the new lot's `original_bu` must not exceed `capacity_bu`, with an exact fit permitted (otherwise `ERR_BIN_CAPACITY_EXCEEDED`); and the lot's crop must equal the bin's crop (otherwise `ERR_CROP_MIX`).

Every fill immediately books **provisional shrink**. Each crop has a standard moisture: 15.0 percent for `CORN`, 13.0 percent for `SOYBEAN`, and 13.5 percent for `WHEAT`. When the lot's fill moisture is strictly greater than its crop's standard, each point of excess (including fractional points) removes 1.35 percent of the original bushels: the shrink is the `original_bu` multiplied by the excess points multiplied by 1.35 and divided by 100, rounded half up to 2 decimal places, and recorded on the lot as `provisional_shrink_bu`. When the fill moisture is at or below the standard, no shrink is booked and `provisional_shrink_bu` is 0.00. The lot's book bushels `current_bu` are its `original_bu` minus this provisional shrink, and whenever the shrink is greater than zero the system posts a `ShrinkEvent` of `kind` `PROVISIONAL` against the lot, with its `shrink_bu` equal to the booked shrink and its `period` null. The lot's `current_moisture_pct` is initialized to the fill moisture, its `drawn_bu`, `cumulative_invisible_loss_bu`, and `cumulative_storage_charge_cents` start at zero, its `months_assessed` counter starts at zero, and its `status` begins at `STORED`. The fill raises the bin's `current_inventory_bu` by the lot's `current_bu` and, because the moisture-and-staleness input set of the bin has changed, triggers a posture recompute.

A lot's `status` thereafter reflects its draw-down: `STORED` until any bushels are drawn, `PARTIALLY_DRAWN` once draws have occurred, `SUSPENDED` whenever its bin's posture gates the site, and `DEPLETED` when its `current_bu` reaches 0.00. Lots may be listed with optional `bin_id`, `status`, `crop`, and `grade` filters plus pagination, and fetched individually by `id`.

### 3.2. Condition Monitoring and Spoilage Alerts

Condition monitoring runs on temperature-cable sweeps. A `SiteManager` ingests a reading with the `bin_id` that was read, the `recorded_at` instant the sweep was taken, the `ambient_temp_f` outside air temperature (1 decimal place, between -40 and 140 inclusive), the `cable_temps_f` array of per-cable grain temperatures (between 1 and 12 entries), and an `insect_activity` flag recording whether insects were observed during the check. Readings may arrive out of order; whenever two readings disagree about which is latest, the system resolves the question by `recorded_at`, never by arrival order. Two readings with an identical `recorded_at` resolve to the one the server accepted later. Each reading stores derived values: `max_cable_temp_f`, the highest entry of the cable array; `temp_delta_f`, the hottest cable minus the ambient temperature; `hotspot_triggered`; and `score_after`, the bin's risk score as recomputed at ingestion.

Ingestion recomputes the bin's **spoilage risk score** from the bin's latest reading by `recorded_at` and from the bin's contributing lots — those not `DEPLETED` with `current_bu` greater than zero. The score is the sum of four terms, rounded half up to 2 decimal places. The temperature term takes the excess of the hottest cable over ambient, subtracts a 10.0-degree-Fahrenheit allowance, divides the result by 20, clamps it to the range from zero to one inclusive, and multiplies by 50. The moisture term computes the bushel-weighted average of the contributing lots' `current_moisture_pct` (each lot weighted by its `current_bu`), subtracts the standard moisture for the bin's crop, divides by 4, clamps to the zero-to-one range, and multiplies by 25. The staleness term counts the whole days — any partial day discarded — between the reading's `recorded_at` and the earliest `fill_date` among the contributing lots, divides by 30, clamps to the zero-to-one range, and multiplies by 15. When no lots contribute, the moisture and staleness terms are both zero. The insect term adds 10 points when the latest reading reports insect activity, and zero otherwise. The result becomes the bin's `risk_score`, and the bin's `insect_activity` and `last_reading_at` are set from the latest reading's flag and `recorded_at`.

A reading is a **hotspot** when the hottest cable exceeds ambient by at least 30.0 degrees Fahrenheit, or when the hottest cable reaches at least 110.0 degrees Fahrenheit — the two tests are independent of the numeric score. A hotspot reading automatically raises a `SpoilageAlert` in `OPEN` status whose `source` is `AUTO_HOTSPOT` (alerts are only ever system-raised), linked to its bin and to the triggering `reading_id`; the alert's `closed_at` stays null while it is open. Because an `OPEN` alert forces the posture ladder to `ALERT`, raising one immediately recomputes the bin's posture and, where the bin was `SOUND` or `WATCH`, fires the gate cascade described in §2.7.

A `SiteManager` closes an open alert by naming an `outcome` of `RESOLVED` or `CONFIRMED_LOSS`. The conditional-field rule is part of request-shape validation and therefore fires before the state check: a closure with outcome `CONFIRMED_LOSS` must carry a `loss_bu` strictly greater than zero (2 decimal places), and a closure with outcome `RESOLVED` must not carry `loss_bu` at all; violations are rejected with `ERR_VALIDATION`. An alert that is no longer `OPEN` cannot be closed and yields `ERR_ALERT_NOT_OPEN`. Closing stamps `closed_at` with the logical clock and recomputes the bin's posture; when the closure lifts the bin back to `SOUND` or `WATCH`, the release cascade of §2.7 runs. Alerts may be listed with optional `bin_id`, `reading_id`, and `status` filters. Readings may be listed with an optional `bin_id` filter, and both resources are individually fetchable.

### 3.3. Fumigation and Restricted-Entry Intervals

When insects take hold, a `CertifiedApplicator` records a fumigation against a bin. The payload names the `bin_id`, the `applicator_id`, the `product` — `PHOSPHINE`, which carries a 72-hour restricted-entry interval, or `SULFURYL_FLUORIDE`, which carries a 24-hour interval — and the occupancy interval from `application_start` to `application_end`, where the end must be strictly later than the start. Segregation begins at creation: the applicator acts as self, so the payload's `applicator_id` must equal the caller's `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN` at the authorization layer, before any existence or shape check. The equality rule applies to a present `applicator_id`; an absent one is a shape defect reported as `ERR_VALIDATION`. The applicator's certification must cover the work — `cert_expires_at` must be at or after `application_start`, otherwise `ERR_APPLICATOR_CERT_EXPIRED` — and an applicator cannot be in two places at once: occupancy intervals are closed, so a new record conflicts with any existing record of the same applicator whenever the new start falls at or before the existing record's end and the existing record's start falls at or before the new end. Touching endpoints conflict; an application beginning at the exact instant another of the applicator's applications ends is rejected with `ERR_APPLICATOR_DOUBLE_BOOKED`.

A created record is immediately `ACTIVE`, with `cleared_at` and `cleared_by_applicator_id` null. Its `lockout_until` is computed as the `application_start` plus the product's restricted-entry interval in hours. Creation recomputes the bin's posture: if the `application_start` is already at or before now, the bin enters `FUMIGATION_LOCKOUT` and the gate cascade fires — lots suspend, scheduled load-outs hold with their bushels released from the contract's commitment, and every `REQUESTED` or `APPROVED` entry permit on the bin is `VOIDED`. A fumigation whose start lies in the future does not lock the bin until the logical clock reaches it, at which point the next posture recompute applies the lockout.

Clearance is segregated from application. A `CertifiedApplicator` clears the record, but the caller's `X-User-ID` must differ from the record's `applicator_id`; the same applicator who applied a fumigation may not clear it, and an attempt is rejected with `ERR_SOD_SAME_APPLICATOR`. Clearance checks only this inequality; the clearing caller is not resolved against the registered applicators. The segregation check precedes the state check: a record that is not `ACTIVE` cannot be cleared and yields `ERR_FUMIGATION_NOT_ACTIVE`, and clearance before the restricted-entry interval has elapsed is rejected with `ERR_REI_NOT_ELAPSED` — the logical clock must be at or after `lockout_until`, and a clearance arriving exactly at `lockout_until` passes. Clearing stamps `cleared_at` with now, records the caller as `cleared_by_applicator_id`, moves the record to `CLEARED`, and recomputes the bin's posture; when the lockout lifts the bin to `SOUND` or `WATCH`, the release cascade runs. Fumigation records may be listed with optional `bin_id`, `applicator_id`, `cleared_by_applicator_id`, and `status` filters.

### 3.4. Bin Entry Permits

Entering a bin — a confined space with engulfment and atmosphere hazards — requires an approved permit. A `SiteManager` or a `SafetyOfficer` requests one by supplying the `bin_id`, the planned window from `planned_start` to `planned_end` (the end strictly later than the start), the pre-entry `atmosphere_test_passed` flag, and the `loto_confirmed` flag attesting that lockout-tagout has been applied to the unloading auger. The request is born `REQUESTED`, and the server records the caller's `X-User-ID` as `requester_user_id`; `approver_user_id` stays null until approval.

Approval belongs to a `SafetyOfficer` and is deliberately segregated: the approver's `X-User-ID` must differ from the `requester_user_id`, even when both hold the same role, and a self-approval attempt is rejected with `ERR_SOD_PERMIT_SELF_APPROVE`. The checks then proceed in a fixed order: the permit must still be `REQUESTED` (otherwise `ERR_PERMIT_NOT_REQUESTED`); no `ACTIVE` fumigation with an `application_start` at or before now may exist on the bin (otherwise `ERR_ACTIVE_FUMIGATION_EXISTS`); and only then are the physical preconditions evaluated — both `atmosphere_test_passed` and `loto_confirmed` must be true, otherwise `ERR_ATMOSPHERE_UNSAFE`. Approval stamps `approver_user_id` with the caller and moves the permit to `APPROVED`.

Permits die two deaths without any client action. A fumigation on the same bin voids every `REQUESTED` and every `APPROVED` permit of that bin, moving them to `VOIDED`, at the moment the bin's posture enters `FUMIGATION_LOCKOUT` — immediately at creation when the `application_start` is already at or before now, otherwise at the first posture recompute after the logical clock reaches it. The monthly assessment sweep expires any `REQUESTED` or `APPROVED` permit whose `planned_end` lies before now, moving it to `EXPIRED`. Both are terminal. Permits may be listed with optional `bin_id` and `status` filters.

### 3.5. Marketing Contracts and Load-Out Scheduling

The `FarmOwner` sells stored grain forward by creating a storage contract: the `crop`; the `contracted_bu` (2 decimal places, strictly greater than zero); the inclusive delivery window from `window_start` through `window_end`, where the end must be strictly later than the start; the locked `basis_cents_per_bu` against futures, which may be negative; and the hedged `futures_ref_cents_per_bu`, strictly greater than zero. Two optional fields price an early-delivery incentive: `early_bonus_cents_per_bu`, defaulting to 0 when omitted, and `early_cutoff`, which may be null — a null cutoff means the contract pays no early bonus at all. The contract's `contract_unit_price_cents` is derived at creation as the futures reference plus the basis. A new contract is `OPEN` with `committed_bu`, `delivered_bu`, and `settled_value_cents` at zero and a `fulfillment_ratio` of 0.0000. The two counters partition the contract's obligations: `committed_bu` sums the `planned_bu` of load-outs whose transport is `SCHEDULED` or `DISPATCHED` — held load-outs are excluded — while `delivered_bu` sums the `settled_net_bu` of load-outs whose settlement is `SETTLED`, and `settled_value_cents` sums their `settlement_net_cents`.

Against an open contract, a `SiteManager` schedules a load-out from a specific bin, supplying the `contract_id`, the source `bin_id`, the half-open load-out window from `scheduled_start` to `scheduled_end` (the end strictly later than the start), the `planned_bu` (2 decimal places, strictly greater than zero), and the `expected_contract_version` required by §2.8. The concurrency check fires immediately after existence resolution and before request-shape validation: a stale version is rejected with `ERR_STALE_CONTRACT_VERSION` even if the payload is otherwise defective. The remaining guards then fire in the global precedence order. The bin's posture must be `SOUND` or `WATCH` (otherwise `ERR_BIN_POSTURE_BLOCKED`). The load-out window must lie entirely within the contract's delivery window — `window_start` at or before `scheduled_start`, and `scheduled_end` at or before `window_end` — otherwise `ERR_OUTSIDE_DELIVERY_WINDOW`. The window must not collide with another live load-out on the same bin: overlap uses half-open semantics over load-outs whose transport is `SCHEDULED`, `HELD`, or `DISPATCHED`, so a conflict exists when the new start falls before an existing window's end and the new end falls after that window's start, while windows that merely touch end-to-start are permitted; a conflict is rejected with `ERR_WINDOW_OVERLAP`. The source bin's crop must equal the contract's crop (otherwise `ERR_CROP_MIX`). The contract must be `OPEN` or `DELIVERING` (otherwise `ERR_CONTRACT_NOT_OPEN`). And the contract must have room: `planned_bu` must not exceed `contracted_bu` minus `committed_bu` minus `delivered_bu` (otherwise `ERR_CONTRACT_REMAINING_EXCEEDED`).

A created load-out starts with `transport_status` `SCHEDULED` and `settlement_status` `UNSETTLED` — two independent, parallel dimensions — with `held_reason` null and no `scale_tickets` yet attached. Its creation adds `planned_bu` to the contract's `committed_bu`, increments the contract's `version`, and moves an `OPEN` contract to `DELIVERING` on its first non-expired load-out. Load-outs may be listed with optional `contract_id`, `bin_id`, `transport_status`, and `settlement_status` filters.

### 3.6. Dispatch, Delivery, and Settlement

The transport dimension walks `SCHEDULED` → `DISPATCHED` → `DELIVERED`, with `HELD` as a posture-driven detour and `EXPIRED` as a sweep-driven terminal. Dispatching is the first gated action: the load-out's transport must be `SCHEDULED` (otherwise `ERR_LOADOUT_STATE`), the bin's posture is re-checked and must be `SOUND` or `WATCH` (otherwise `ERR_BIN_POSTURE_BLOCKED`), and the contract must still be `OPEN` or `DELIVERING` (otherwise `ERR_CONTRACT_NOT_OPEN`). A successful dispatch moves the transport to `DISPATCHED`. Posture cascades can interrupt this path: a bin entering `ALERT` or `FUMIGATION_LOCKOUT` holds its `SCHEDULED` load-outs (transport to `HELD`, `held_reason` set to `POSTURE`, each subtracting its `planned_bu` from the contract's `committed_bu` and incrementing the contract's `version`), and a bin releasing back to `SOUND` or `WATCH` returns them (transport to `SCHEDULED`, `held_reason` cleared, commitment and version restored symmetrically). Already-dispatched load-outs are not held.

Delivery converts truck scale tickets into settled bushels. A `SiteManager` delivers a `DISPATCHED` load-out — any other transport state yields `ERR_LOADOUT_STATE` — by supplying the actual `delivered_at` timestamp and the `scale_tickets` array, each ticket carrying a `ticket_no` (a string or an integer), a `gross_bu`, and a `moisture_pct`. The shape rules — which per §2.9 fire before the `DISPATCHED` state check — reject a delivery with `ERR_VALIDATION` when the array is empty, when a `ticket_no` repeats within the load-out, when a `gross_bu` is not strictly greater than zero, or when a `moisture_pct` falls outside 0 to 40 inclusive. **Settlement shrink** is then computed per ticket and the rounding order is pinned: for each ticket, in array order, the shrink is the ticket's gross bushels multiplied by the excess of its moisture over the contract crop's standard moisture — floored at zero, so at-or-below-standard moisture shrinks nothing — multiplied by 1.35 and divided by 100, rounded half up to 2 decimal places; each ticket's net is its gross minus its own shrink, itself rounded half up to 2 decimal places. The load-out's `ticket_shrink_bu` is the sum of the per-ticket shrinks, its `settled_net_bu` is the sum of the per-ticket nets, and its `gross_bu` is the sum of the ticket grosses — rounding each ticket before summing is mandatory, because summing first and rounding the load-out total produces a different number and is forbidden. Delivery records `delivered_at` and moves the transport to `DELIVERED`.

Confirmation turns delivered bushels into money and lot draw-downs. Confirming a settlement requires the transport to be `DELIVERED` (otherwise `ERR_LOADOUT_STATE`), the settlement dimension to be `UNSETTLED` (otherwise `ERR_SETTLEMENT_STATE`), and the contract to be `OPEN` or `DELIVERING` (otherwise `ERR_CONTRACT_NOT_OPEN`), in that order. The **allocation waterfall** then debits lots from the load-out's bin: eligible lots are those in `STORED` or `PARTIALLY_DRAWN` status with `current_bu` greater than zero — `SUSPENDED` and `DEPLETED` lots never contribute — ordered by `fill_date` ascending with `created_at` ascending as the tie-break — lots sharing both break the remaining tie by server acceptance order — never by identifier. When the eligible bushels cannot cover the load-out's `settled_net_bu`, the confirmation is rejected with `ERR_LOTS_INSUFFICIENT` and nothing is debited. Otherwise the waterfall walks the ordered lots, taking from each the lesser of its `current_bu` and the remaining demand: each take is subtracted from the lot's `current_bu`, added to its `drawn_bu`, and recorded on the load-out's `draws` array as a `lot_id`-and-`bu` entry. A lot drawn to exactly 0.00 becomes `DEPLETED`; any lot from which a positive amount was taken without depletion becomes `PARTIALLY_DRAWN`.

The money side of confirmation — **settlement charges** — has a pinned evaluation order keyed on the pre-fee grain value. First, `grain_value_cents` is the load-out's `settled_net_bu` multiplied by the contract's `contract_unit_price_cents`, rounded half up to whole cents. Second, the service-fee rate is selected by where that pre-fee value falls: below 200,000 cents the rate is 150 basis points; from 200,000 cents up to but not including 500,000 cents the rate is 100 basis points; at or above 500,000 cents the rate is 75 basis points — a grain value of exactly 500,000 cents takes the 75-basis-point tier. Third, `service_fee_cents` is the grain value multiplied by the selected basis-point rate and divided by 10,000, rounded half up to whole cents. Fourth, `early_bonus_cents` is the `settled_net_bu` multiplied by the contract's `early_bonus_cents_per_bu` when the contract has a non-null `early_cutoff` and the `delivered_at` is at or before that cutoff, and zero otherwise. Fifth, `settlement_net_cents` is the grain value minus the service fee plus the early bonus. All monetary results are integer cents, rounded half up.

Confirmation accumulates onto the contract: `delivered_bu` increases by the `settled_net_bu`, `settled_value_cents` increases by the `settlement_net_cents`, the contract's `version` increments, and the settlement dimension moves to `SETTLED`. Fulfillment is judged in bushels, not ratio points: when the contract's `delivered_bu` reaches at least 98 percent of its `contracted_bu` — exactly 98.00 percent fulfills, 97.99 percent does not — the contract moves from `DELIVERING` to `FULFILLED`, with the `fulfillment_ratio` maintained at 4 decimal places as delivered divided by contracted. The bin's `current_inventory_bu` and posture are recomputed to close the loop.

A settlement can later be undone by voiding, which requires the settlement dimension to be `SETTLED` (otherwise `ERR_SETTLEMENT_STATE`). Voiding is a compensating reversal that restores every invariant: each recorded draw is reversed — the lot's `current_bu` is credited back and its `drawn_bu` debited, so a `DEPLETED` lot revives to `PARTIALLY_DRAWN`, and a `PARTIALLY_DRAWN` lot whose `drawn_bu` returns to zero becomes `STORED` again, except that a lot revived while its bin's posture is `ALERT` or `FUMIGATION_LOCKOUT` becomes `SUSPENDED` instead and remains gated until the release cascade — the contract's `delivered_bu` and `settled_value_cents` are reduced by the load-out's settled quantities, the contract's `version` increments, a contract that had reached `FULFILLED` falls back to `DELIVERING` when the reversal drops its delivered bushels below the 98-percent threshold, the settlement dimension moves to `VOIDED`, and the bin's inventory and posture are recomputed. The transport dimension is unaffected: a load-out whose transport is `DELIVERED` stays `DELIVERED` while its settlement moves from `UNSETTLED` to `SETTLED` to `VOIDED`. The load-out's `draws` array and settlement money fields are retained after voiding as the audit record of what was reversed.

The monthly sweep closes the transport dimension for stragglers: a `SCHEDULED` load-out whose `scheduled_end` lies before now expires, releasing its `planned_bu` from the contract's `committed_bu` and incrementing the contract's `version`, while a `HELD` load-out expiring carries no such release because held load-outs are already excluded from the commitment.

### 3.7. The Monthly Assessment Epoch

Once per calendar month of operation, a `SiteManager` runs the assessment epoch for a `period` named by its month in YYYY-MM form; a malformed `period` is a shape defect rejected with `ERR_VALIDATION` (HTTP 400) before the uniqueness check. The period is globally unique — it serves as the idempotency key for the whole epoch — and a repeat submission is rejected with `ERR_ASSESSMENT_EXISTS`.

The epoch charges storage and posts invisible loss, lot by lot. Eligible lots are those with `current_bu` greater than zero whose fill month is the assessment month or earlier. For each eligible lot, in creation order (`created_at` ascending), the charge is computed from the pre-loss balance: the months-since-fill figure is twelve times the difference in calendar years plus the difference in calendar months between the assessment period and the lot's fill month; the rate is 3 cents per bushel per month when that figure is 3 or less, 4 cents when it is 4 to 6 inclusive, and 5 cents when it is 7 or more; the charge is the lot's pre-loss `current_bu` multiplied by the rate, rounded half up to whole cents. The charge accumulates into the lot's `cumulative_storage_charge_cents`, and its `months_assessed` increments by one. Then the month's **invisible loss** comes out of the same pre-loss balance: the loss is the pre-loss `current_bu` multiplied by 0.20 percent, rounded half up to 2 decimal places; when the loss is greater than zero the system posts a `ShrinkEvent` of `kind` `INVISIBLE_LOSS` with the assessment's `period` recorded on it; the lot's `current_bu` is reduced by the loss and its `cumulative_invisible_loss_bu` accumulates it. A lot whose balance falls to zero or below is floored at exactly 0.00 and becomes `DEPLETED` — including a `STORED` lot that invisible loss alone depletes without any draws.

The epoch then sweeps every time-boxed obligation against the logical clock. Contracts in `OPEN` or `DELIVERING` whose `window_end` lies before now are judged: those whose `delivered_bu` reaches at least 98 percent of `contracted_bu` move to `FULFILLED`, the rest move to `DEFAULTED`, and each swept contract's `version` increments. Load-outs in `SCHEDULED` or `HELD` whose `scheduled_end` lies before now move to `EXPIRED`, with the commitment release described in §3.6 applying to the `SCHEDULED` ones. Permits in `REQUESTED` or `APPROVED` whose `planned_end` lies before now move to `EXPIRED`. Insurance policies that are `ACTIVE` with a `period_end` before now move to `EXPIRED`. Finally, every bin's posture is recomputed — the epoch is a posture trigger for all bins, so a fumigation whose `application_start` the clock has passed engages its lockout here — and the `current_inventory_bu` of every bin whose lots moved is recomputed.

The epoch's product is a `StorageAssessment` record — an immutable audit row — carrying the `period` and the run's tallies: `lots_assessed` (the number of eligible lots processed in this run — every eligible lot is charged, even when the charge rounds to zero cents, and counted), `total_storage_charge_cents`, `total_invisible_loss_bu`, `contracts_defaulted`, `contracts_fulfilled`, `permits_expired`, `loadouts_expired`, and `policies_expired`. The full shrink history of any lot — both `PROVISIONAL` and `INVISIBLE_LOSS` events, each with its `lot_id`, `kind`, `shrink_bu`, and `period` (null on provisional events) — is retrievable through the lot's shrink-event listing, which accepts an optional `kind` filter.

### 3.8. Insurance Policies and Spoilage Claims

A `FarmOwner` insures stored grain by creating a policy: the covered `crop`; the aggregate `coverage_limit_cents`, strictly greater than zero; the per-claim `deductible_cents`, which may be zero and is applied after the coverage cap; the `valuation_clause` of `SPOT` or `CONTRACT_AVG`; and the inclusive coverage period from `period_start` through `period_end`, where the end must be strictly later than the start. A new policy is `ACTIVE` with `remaining_coverage_cents` equal to its full `coverage_limit_cents`.

When a spoilage alert has closed with a confirmed loss, a `SiteManager` submits a claim naming the `policy_id` and the `spoilage_alert_id`. The guards fire in precedence order after existence and shape: the alert's `closed_at` must fall within the policy's coverage period, both bounds inclusive (otherwise `ERR_LOSS_OUTSIDE_PERIOD`) — an alert that has never closed has no `closed_at`, so the period check does not bind and the `CONFIRMED_LOSS` requirement below reports it instead; the policy's crop must equal the crop of the bin that raised the alert (otherwise `ERR_CROP_MIX`); the referenced alert must be in `CONFIRMED_LOSS` (otherwise `ERR_ALERT_LOSS_NOT_CONFIRMED`); and the policy must be `ACTIVE` (otherwise `ERR_POLICY_NOT_ACTIVE`). A submitted claim copies the alert's `loss_bu` onto itself and begins in `SUBMITTED` status.

Approval belongs to the `FarmOwner`. The conditional input rule is shape-level and precedes the state check: under a `SPOT` valuation clause the approval payload must carry `spot_price_cents_per_bu`; under `CONTRACT_AVG` it must not, except when the valuation pool defined below is empty — the fallback case in which the clause behaves as `SPOT` and the spot price input is then required; and a violation is rejected with `ERR_VALIDATION`; a claim that is not `SUBMITTED` yields `ERR_CLAIM_NOT_SUBMITTED`. The indemnity then values the loss per the policy's clause. Under `SPOT`, the claim's `unit_value_cents` is the supplied spot price. Under `CONTRACT_AVG`, the valuation pool is every contract of the policy's crop in `OPEN` or `DELIVERING` status whose delivery window contains the alert's `closed_at`, both bounds inclusive; when the pool is empty the clause falls back to `SPOT` behavior and the spot price input is then required; otherwise the `unit_value_cents` is the contracted-bushel-weighted average of the pool's unit prices — the sum over the pool of each contract's `contract_unit_price_cents` multiplied by its `contracted_bu`, divided by the sum of the pool's `contracted_bu` — carried at 2 decimal places. The `gross_indemnity_cents` is the `loss_bu` multiplied by the `unit_value_cents`, rounded half up to whole cents. The payable `indemnity_cents` applies the coverage cap before the deductible: it is the lesser of the gross indemnity and the policy's `remaining_coverage_cents`, minus the `deductible_cents`, floored at zero. Approval moves the claim to `APPROVED`, reduces the policy's `remaining_coverage_cents` by the indemnity paid, and increments the policy's `version`. Claims may be listed with optional `policy_id`, `spoilage_alert_id`, and `status` filters.

### 3.9. Carry Analysis: Holding Versus Selling

For any lot, a `SiteManager` or `FarmOwner` can ask whether holding the grain one more month earns more than it costs. The capability takes two required query parameters: `current_basis_cents`, the integer basis prevailing in the local market, and `variant`, one of `CASH` or `ECONOMIC`; a missing, non-integer, or out-of-enum value is rejected with `ERR_VALIDATION` (HTTP 400).

The analysis works forward from the logical clock. Months held is computed in the same calendar arithmetic as the assessment epoch: twelve times the difference in calendar years plus the difference in calendar months between now and the lot's fill month. The same rate ladder applies — 3 cents per bushel per month through month 3, 4 cents through month 6, and 5 cents beyond. The lot's `storage_paid_cents` is simply its `cumulative_storage_charge_cents`, what the operation has already paid. The `projected_month_charge_cents` is the lot's `current_bu` multiplied by the rate for its months-held tier, rounded half up to whole cents. The `basis_gain_cents` is the improvement in basis since fill — the `current_basis_cents` minus the lot's `fill_basis_cents` — multiplied by the lot's `current_bu`, rounded half up to whole cents; a weakening basis makes this figure negative. The `interest_cents` depends on the variant: under `CASH` it is zero, excluding financing opportunity cost entirely; under `ECONOMIC` it is the lot's `current_bu` multiplied by its `reference_price_cents_per_bu`, multiplied by 6 percent per annum, multiplied by the whole days between `fill_date` and now (any partial day discarded) divided by 365, rounded half up to whole cents. The `net_carry_cents` is the basis gain minus the storage already paid, minus the projected month charge, minus the interest. The `recommendation` is `HOLD` when the net is strictly greater than zero and `SELL` when it is zero or negative — an exactly break-even carry sells. Because the `ECONOMIC` variant subtracts a financing term that `CASH` ignores, identical inputs can legitimately produce `HOLD` under one variant and `SELL` under the other. The response reports the `lot_id`, the `variant` evaluated, the lot's `current_bu`, and each computed component alongside the recommendation.

## 4. Endpoint Definitions

All business endpoints are mounted under the `/grain` prefix. Operations that create a new resource return `201 Created`; operations that modify an existing resource, and all reads, return `200 OK`. The table below is a routing summary only — request payloads, derived fields, side effects, and error conditions are defined by the workflow narratives in §3 and the principles in §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/grain/bins` | Create a bin | SiteManager |
| GET | `/grain/bins/{id}` | Get a bin (posture, risk score, inventory) | All roles |
| POST | `/grain/lots` | Bin a grain lot (fill) | SiteManager |
| GET | `/grain/lots/{id}` | Get a lot | All roles |
| GET | `/grain/lots` | List lots with filters and pagination | All roles |
| GET | `/grain/lots/{id}/carry-analysis` | Storage-cost vs basis-gain decision for a lot | SiteManager, FarmOwner |
| GET | `/grain/lots/{id}/shrink-events` | List shrink events for a lot (audit trail) | All roles |
| POST | `/grain/temperature-readings` | Ingest a temperature-cable reading; recomputes risk score, raises hotspot alerts | SiteManager |
| GET | `/grain/temperature-readings/{id}` | Get a reading | All roles |
| GET | `/grain/temperature-readings` | List readings | All roles |
| GET | `/grain/spoilage-alerts/{id}` | Get an alert | All roles |
| GET | `/grain/spoilage-alerts` | List alerts | All roles |
| POST | `/grain/spoilage-alerts/{id}/close` | Close an alert as RESOLVED or CONFIRMED_LOSS | SiteManager |
| POST | `/grain/fumigations` | Create a fumigation record (immediately ACTIVE; caller is the applicator) | CertifiedApplicator |
| GET | `/grain/fumigations/{id}` | Get a fumigation record | All roles |
| GET | `/grain/fumigations` | List fumigation records | All roles |
| POST | `/grain/fumigations/{id}/clear` | Clear a fumigation after the REI (segregated from applicator) | CertifiedApplicator |
| POST | `/grain/entry-permits` | Request a bin-entry permit | SiteManager, SafetyOfficer |
| GET | `/grain/entry-permits/{id}` | Get a permit | All roles |
| GET | `/grain/entry-permits` | List permits | All roles |
| POST | `/grain/entry-permits/{id}/approve` | Approve a permit (segregated from requester) | SafetyOfficer |
| POST | `/grain/contracts` | Create a storage/delivery contract | FarmOwner |
| GET | `/grain/contracts/{id}` | Get a contract (version, committed/delivered, ratio, status) | All roles |
| POST | `/grain/loadouts` | Schedule a load-out against a contract from a bin (OCC on contract version) | SiteManager |
| GET | `/grain/loadouts/{id}` | Get a load-out | All roles |
| GET | `/grain/loadouts` | List load-outs | All roles |
| POST | `/grain/loadouts/{id}/dispatch` | Dispatch a scheduled load-out | SiteManager |
| POST | `/grain/loadouts/{id}/deliver` | Record scale tickets; computes per-ticket settlement shrink | SiteManager |
| POST | `/grain/loadouts/{id}/confirm-settlement` | Settle: money calculation, lot waterfall debit, contract accumulation | SiteManager |
| POST | `/grain/loadouts/{id}/void-settlement` | Compensating reversal of a settlement | SiteManager |
| POST | `/grain/policies` | Create an insurance policy (immediately ACTIVE) | FarmOwner |
| POST | `/grain/claims` | Submit a claim against a CONFIRMED_LOSS alert | SiteManager |
| GET | `/grain/claims/{id}` | Get a claim | All roles |
| GET | `/grain/claims` | List claims | All roles |
| POST | `/grain/claims/{id}/approve` | Approve a claim; computes indemnity and debits coverage | FarmOwner |
| POST | `/grain/applicators` | Register a certified applicator | SiteManager |
| POST | `/grain/assessments` | Run the monthly assessment epoch (period unique) | SiteManager |
| POST | `/_clock/set_current_utc` | Set the logical clock | SiteManager |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SOD_SAME_APPLICATOR` | 403 Forbidden |
| `ERR_SOD_PERMIT_SELF_APPROVE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_CONTRACT_VERSION` | 412 Precondition Failed |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_ALERT_NOT_OPEN` | 409 Conflict |
| `ERR_FUMIGATION_NOT_ACTIVE` | 409 Conflict |
| `ERR_PERMIT_NOT_REQUESTED` | 409 Conflict |
| `ERR_CLAIM_NOT_SUBMITTED` | 409 Conflict |
| `ERR_LOADOUT_STATE` | 409 Conflict |
| `ERR_SETTLEMENT_STATE` | 409 Conflict |
| `ERR_BIN_POSTURE_BLOCKED` | 409 Conflict |
| `ERR_ACTIVE_FUMIGATION_EXISTS` | 409 Conflict |
| `ERR_REI_NOT_ELAPSED` | 409 Conflict |
| `ERR_APPLICATOR_CERT_EXPIRED` | 409 Conflict |
| `ERR_ATMOSPHERE_UNSAFE` | 409 Conflict |
| `ERR_OUTSIDE_DELIVERY_WINDOW` | 409 Conflict |
| `ERR_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_APPLICATOR_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_LOSS_OUTSIDE_PERIOD` | 409 Conflict |
| `ERR_BIN_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_CROP_MIX` | 409 Conflict |
| `ERR_ASSESSMENT_EXISTS` | 409 Conflict |
| `ERR_ALERT_LOSS_NOT_CONFIRMED` | 409 Conflict |
| `ERR_POLICY_NOT_ACTIVE` | 409 Conflict |
| `ERR_CONTRACT_NOT_OPEN` | 409 Conflict |
| `ERR_LOTS_INSUFFICIENT` | 409 Conflict |
| `ERR_CONTRACT_REMAINING_EXCEEDED` | 409 Conflict |
