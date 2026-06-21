# Homeowners Insurance Underwriting API — Product Requirements Document

## 1. Introduction

This document specifies the Homeowners Insurance Underwriting API, a back-office platform that carries a residential property from initial intake through a fully bound, paid, and serviceable policy. Underwriting a dwelling is not a single decision but a sequence of gated steps: an estimator establishes how much it would cost to rebuild the structure, a risk team scores the property's exposure to wildfire, flood, and coastal wind, a field inspector verifies the home's four major systems, and only then may a licensed underwriter price and bind the risk. Each of these steps produces an auditable artifact, and each gate can reject the application for a concrete, recorded reason.

The platform is built around a strict separation of duties. The producing agent who originates business — creating the property record, requesting estimates, assembling the application, and tendering money — is never the same person who accepts the risk on behalf of the carrier. Binding, declining, lapsing, and cancelling are reserved for underwriters, and field verification is reserved for inspectors. The system also treats money as a conserved quantity: every premium movement is recorded as a ledger posting, and every reversible action (an endorsement removed, a policy lapsed) is backed by a compensating posting so that balances never drift. Two families of figures — the replacement cost of the dwelling and the wildfire score of its surroundings — are computed twice over a property's life, once provisionally at intake and once finally after physical inspection, and the difference between those two figures is what ultimately decides whether a home is insurable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint. Where a business rule is sketched here, the full workflow narrative in Section 3 supplies its operational context.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers that together establish the caller's identity and capacity: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the role under which they are acting. A request that omits either header, or supplies a value that is not recognized, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles: `Admin`, `Agent`, `Underwriter`, and `Inspector`.

The way `X-User-ID` is interpreted depends on the role. When `X-User-Role` is `Underwriter`, `X-User-ID` is the `id` of the acting `Underwriter` entity; ownership checks compare a resource's underwriter foreign key to this value — in particular, an application's `assigned_underwriter_id` is matched against the acting underwriter's `X-User-ID` on every review action. When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting `Inspector` entity, and the inspector's own buffer and schedule are resolved through that identity. When `X-User-Role` is `Admin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server accepts it for the audit record but does not compare it to any entity's `id`. When `X-User-Role` is `Agent`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server records it — for example, as the `agent_id` stamped onto an application at creation time — but never resolves it to a stored agent row.

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

List endpoints accept two query parameters to page through results. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip from the start of the result set and defaults to 0.

Unless an endpoint states otherwise, list results are sorted by `created_at` in ascending order, so the oldest record appears first. Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identity

Every persisted resource carries an `id`, which is a server-minted UUID with no type prefix, and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits recording when the resource was first stored. Most resources additionally carry an `updated_at` timestamp, refreshed on every mutation under the same format, and a `version`, an integer that begins at its initial value and increments by one on each mutation of the resource.

One entity is the exception to the `updated_at`/`version` rule. The `Underwriter` entity is immutable after creation: it exposes only `id` and `created_at`, and carries neither an `updated_at` field nor a `version` field. Every other entity in the system — `Property`, `RiskAssessment`, `Inspector`, `Inspection`, `Application`, `Endorsement`, `Quote`, `Policy`, and `Payment` — carries the full quartet of common fields.

When a derived field is recomputed as a side effect of some operation — for example, when a property's `total_insured_value` is refreshed, or a policy's `premium_balance` is recomputed after a ledger posting — that recomputation counts as a mutation of the owning resource: it refreshes `updated_at` and increments `version`.

### 2.5. Resource Lifecycle, Archiving, and Left-to-Right Resolution

`Property`, `Inspector` records carry a system-managed `status` of either `ACTIVE` or `ARCHIVED`, beginning at `ACTIVE`. Archived records are excluded from default list results; the property list endpoint re-includes them only when the caller passes `include_archived` set to true.

This is a flat topology: every entity is a top-level collection, and resources reference one another through foreign-key fields carried in request bodies rather than through nested URL ownership. Nevertheless, when an operation names more than one resource — by a path identifier and one or more body identifiers — the server validates their existence left to right, path identifier first, and returns the not-found error for the first identifier that fails to resolve. Each persisted resource has its own not-found code: `ERR_PROPERTY_NOT_FOUND`, `ERR_RISK_ASSESSMENT_NOT_FOUND`, `ERR_INSPECTOR_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_ENDORSEMENT_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_PAYMENT_NOT_FOUND`, and `ERR_UNDERWRITER_NOT_FOUND`.

### 2.6. Validation Order and Input Integrity

When several checks could reject the same request, the system evaluates them in a fixed priority order so that the rejection a caller receives is deterministic. Authentication comes first: the presence and validity of `X-User-ID` and `X-User-Role` is checked before anything else, and a failure here yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Authorization is second — whether the acting role may perform this operation at all, failing with `ERR_UNAUTHORIZED`. Third, the existence of every referenced resource id is confirmed, left to right, with the appropriate not-found code. Fourth, the target resource's state is checked for fitness for the operation (for example, an application must be `UNDER_REVIEW` to be bound, a policy must be `PENDING_PAYMENT` to accept a binding payment, an inspection must be `SCHEDULED` to be completed), yielding the operation-specific state conflict code. Only after these gates pass does the system evaluate business-referential, safety, temporal, fiscal, and constraint rules — described throughout Section 3 — in that relative order.

The lowest-priority gate is generic input integrity. Whenever a request body carries a malformed value — an unrecognized enum member, a numeric field outside its permitted range, an inspection whose `window_end` is not strictly greater than its `window_start`, a policy whose `expiration_date` is not strictly greater than its `effective_date`, a `wind_hail_deductible_pct` that is not one of the three permitted values, or a missing required field — the request is rejected with `ERR_INVALID_REQUEST`. Because this gate sits below the state and business gates, a request that is both ill-formed and, say, in the wrong state surfaces the higher-priority rejection first.

### 2.7. Premium Precision and Rounding

All monetary figures are carried to two decimal places using the round-half-up convention. The rounding is applied per component, and the order in which it is applied is fixed because rounding-then-summing and summing-then-rounding can differ by a cent. Specifically, when a quote's annual figure is assembled, the base portion is rounded to two decimal places to produce `base_premium`, the endorsement portion is independently rounded to two decimal places to produce `endorsement_premium`, and only then are those two already-rounded amounts added together to yield `annual_premium`. The system commits this round-each-component-then-sum order; it does not sum the raw components and round once at the end. Every individual endorsement's `premium_delta` is itself rounded to two decimal places when it is computed, so the endorsement portion is a sum of already-rounded deltas. Ledger-derived balances such as `premium_balance` are likewise maintained at two decimal places.

### 2.8. The Premium Ledger and Conservation of Balance

Each bound policy owns an internal, append-only ledger of premium postings. A posting is either a DEBIT, which raises what the policyholder owes, or a CREDIT, which lowers it. The policy's `premium_balance` is a conserved, read-only quantity equal to the sum of all DEBIT postings minus the sum of all CREDIT postings over that policy's ledger; no posting is ever excluded from the running total. The ledger is the single source of truth for the balance, and the balance is recomputed from it after every posting.

Conservation is a hard invariant: every action that posts to the ledger and is later reversed must be backed by a compensating posting of equal magnitude and opposite sign, so that a forward posting plus its reversal nets to zero change in `premium_balance`. This governs the endorsement-removal and lapse flows described in Section 3 — a removed endorsement leaves the balance exactly where it would have been had the endorsement never applied, and a lapse writes the balance back to zero through an offsetting credit.

### 2.9. Optimistic Concurrency on Binding and Lapsing

Two operations in the system are guarded by optimistic concurrency control, each requiring the caller to declare the version of the parent record they believe they are acting on.

Binding an application requires the caller to supply `expected_application_version`, carrying the `version` of the `Application` that the binder last observed. If that value does not match the application's current `version` — which happens when another writer has advanced the application since the binder last read it, for instance through a return-to-queue and re-take cycle or a re-submission that regenerated the quote — the bind is rejected with `ERR_STALE_APPLICATION_VERSION` at HTTP 412, preventing the binder from committing a decision against a view of the application it never actually saw.

Lapsing a policy requires the caller to supply `expected_policy_version`, carrying the `version` of the `Policy` the caller last observed. If that value does not match the policy's current `version` — which happens when another writer has already advanced the policy, for instance by lapsing and reinstating it — the lapse is rejected with `ERR_STALE_POLICY_VERSION` at HTTP 412. These two endpoints are the only ones that take a version field; no other operation requires or accepts one.

### 2.10. Coverage Conservation: Replacement Cost and Total Insured Value

A property carries two derived dollar figures that the system keeps internally consistent. The `replacement_cost` is the latest committed Coverage A (dwelling) estimate; it is read-only and reads 0 until an estimate has been committed, at which point the `estimate_variant` field records which of the two estimation methods produced it (`COMPONENT`, `SQFT_BLEND`, or `NONE` before any commit). The `total_insured_value` is a conserved quantity equal to the `replacement_cost` plus the sum of `coverage_limit` across every PERIL_ADD endorsement that has reached `APPLIED` status on the property's bound policy. It starts at 0, and committing a replacement-cost estimate resets it to the freshly committed `replacement_cost`. Thereafter it moves only as applied perils are added or reversed, as detailed in Section 3.

## 3. Business Logic & Workflows

### 3.1. Establishing the Property and Its Replacement Cost

Underwriting begins when a producing agent records the dwelling. A property is created with its `street_address`, its two-letter `state_code`, the `year_built`, the living-area `square_footage`, the `construction_type`, and the `roof_age_years`. The number of `stories` is optional and is taken to be 1 when omitted. The year built must fall on or after 1800 and on or before 2026; square footage must be a positive number; roof age must be zero or greater; and stories, when supplied, must be at least 1. The `construction_type` is one of `FRAME`, `MASONRY`, or `FIRE_RESISTIVE`, and it drives the per-square-foot and component rates used downstream. A newly created property starts `ACTIVE`, with `replacement_cost` at 0, `total_insured_value` at 0, and `estimate_variant` at `NONE`.

Before an application on a property can be submitted, the dwelling must have a committed replacement-cost estimate. The agent requests one by choosing a `method`, which selects the estimation variant; the two variants deliberately produce different Coverage A figures for identical property inputs, and the committed value together with its `estimate_variant` is stored on the property. Both variants begin from two shared quantities. The base rate is the per-square-foot construction rate for the property's construction type, which is 120 for `FRAME`, 150 for `MASONRY`, and 185 for `FIRE_RESISTIVE`. The story factor is one plus four hundredths multiplied by the number of stories beyond the first — that is, the per-story step of 0.04 is applied once for each story above one.

Under the component method (`method` equal to `COMPONENT`), the structure cost is the base rate multiplied by the square footage and then by the story factor. The roof is costed separately: a roof replacement figure is formed by multiplying the square footage by the per-square-foot roof rate for the construction type, which is 18 for `FRAME`, 22 for `MASONRY`, and 26 for `FIRE_RESISTIVE`. That roof figure is then adjusted downward for age — a newer roof costs more to match — by multiplying it by one minus one hundredth of the roof age in years, where the roof age used is capped at 20 even if the actual roof is older. The committed replacement cost is the structure cost plus the age-adjusted roof figure, rounded half up to two decimal places, and the variant recorded is `COMPONENT`.

Under the square-foot blend method (`method` equal to `SQFT_BLEND`), there is no separate roof line; instead the base rate is lifted by a blend uplift factor for the construction type — 1.18 for `FRAME`, 1.16 for `MASONRY`, and 1.15 for `FIRE_RESISTIVE` — to fold the roof into a single blended per-square-foot rate. The committed replacement cost is that blended rate multiplied by the square footage and by the story factor, rounded half up to two decimal places, and the variant recorded is `SQFT_BLEND`. Because the blend folds the roof in without any age depreciation, the same property generally yields a different dollar value under each method. Committing either estimate sets `replacement_cost`, sets `estimate_variant`, and resets `total_insured_value` to the new `replacement_cost`.

### 3.2. Scoring Risk: Wildfire, Flood, and Coastal Wind

A property's exposure is captured by a risk assessment, authored by an underwriter, that names the `property_id` it scores and supplies five environmental inputs: the surrounding-vegetation `wildfire_fuel_density` on a 0-to-100 scale, the terrain `slope_grade_pct` on a 0-to-100 scale, the cleared `defensible_space_ft` (zero or greater), the FEMA `flood_zone`, and the `distance_to_coast_mi` (zero or greater). The flood zone is one of `X`, `A`, `AE`, or `VE`. Creating the assessment computes two read-only figures and stamps the stage.

The wildfire score begins from a raw weighted figure: seven tenths of the fuel density plus one half of the slope grade, minus three tenths of the defensible space in feet, where the defensible space used in that subtraction is capped at 200 feet even when more land has been cleared. At creation the assessment is `PROVISIONAL`: the provisional `wildfire_score` is that raw figure rounded half up to the nearest integer and then clamped to the range 0 through 100. The provisional score carries no mitigation credit, which is why it runs higher and reflects the pre-inspection risk view. The score's `score_stage` starts at `PROVISIONAL` and becomes `FINAL` only when the property's inspection passes, at which point the score is recomputed under the final variant: the same rounded raw figure, less a verified-mitigation credit of 12 points, then clamped to the range 0 through 100. Rounding to the integer happens before the clamp in both variants. This lower final value is the one weighed against the insurability boundary at binding time.

The wind/hail tier is derived purely from the distance to the coast, on the principle that a closer coast means higher wind and hail risk. The tier is `TIER_3` when the distance to coast is strictly less than 5 miles, `TIER_2` when the distance is at least 5 miles and at most 50 miles, and `TIER_1` when the distance is strictly greater than 50 miles. The resulting `wind_hail_tier` feeds the premium calculation. The assessment's own `status` follows the standard `ACTIVE`/`ARCHIVED` lifecycle for top-level records.

### 3.3. Field Verification: The Four-Point Inspection

Field inspectors are provisioned by an administrator, who records each inspector's `full_name`, the two-letter `license_state` they are licensed in, and optionally their travel `buffer_minutes`. To verify the dwelling's condition, an underwriter schedules a four-point inspection that names the `property_id` and the `inspector_id`, along with the inspection window expressed as Unix epoch seconds in `window_start` and `window_end`. The window is half-open, covering the start instant up to but not including the end instant, and the end must be strictly greater than the start. A freshly scheduled inspection is `SCHEDULED`, with its four condition flags — `roof_ok`, `electrical_ok`, `plumbing_ok`, and `hvac_ok` — defaulting to false and `passed_count` at 0.

Each inspector enforces a mandatory travel buffer, a `buffer_minutes` value that defaults to 60 minutes and that must separate two inspections by the same inspector. When an inspection is scheduled, or when a failed one is rescheduled, the system rejects a window that falls within the inspector's buffer of any other `SCHEDULED`, `COMPLETED`, or `PASSED` inspection already on that inspector's calendar, surfacing `ERR_INSPECTION_WINDOW_CONFLICT`. Two windows conflict when, after expanding each by the buffer gap, the half-open intervals would touch or overlap; the buffer is applied as a minutes gap between the end of one window and the start of the next.

When the field visit is done, the inspector completes the inspection, supplying the four boolean results `roof_ok`, `electrical_ok`, `plumbing_ok`, and `hvac_ok`. Completion is permitted only from `SCHEDULED`, otherwise `ERR_INSPECTION_NOT_SCHEDULED`. On completion the `passed_count` is set to the number of the four points that are true, and the system then resolves the inspection automatically: when all four points are true — that is, when the passed count equals 4 — the inspection moves to `PASSED`; when fewer than four points are true the inspection moves to `FAILED`. The boundary is exact: three passing points fail, four pass. The transition to `PASSED` is the event that finalizes the property's wildfire score — it flips every risk assessment recorded against that `property_id` to `score_stage` `FINAL` and recomputes each one's `wildfire_score` under the final, mitigation-credited variant; if no risk assessment exists for the property yet, the pass simply completes with nothing to finalize.

A failed inspection can be reworked. The inspector reschedules it, supplying a fresh `window_start` and `window_end`; this is allowed only from `FAILED`, otherwise `ERR_INSPECTION_NOT_FAILED`, and the new window is re-checked against the same inspector buffer-conflict rule. Rescheduling returns the inspection to `SCHEDULED`, resets all four condition flags to false, and resets `passed_count` to 0, so the re-inspection starts clean.

### 3.4. Assembling and Pricing the Application

A producing agent opens an application against a property by naming the `property_id` and the `requested_coverage_a`, the dwelling limit the policyholder is asking for, which must be a number of zero or greater at creation (a negative value is rejected with `ERR_INVALID_REQUEST`). The wind/hail percentage deductible, `wind_hail_deductible_pct`, is optional and defaults to 2; it must be one of 1, 2, or 5, expressed as a percent of Coverage A. A new application is `DRAFT`; its `agent_id` is stamped from the creating agent's `X-User-ID`, its `quoted_premium` starts at 0, its `decline_reason` starts at `NONE`, and its `assigned_underwriter_id` is null until an underwriter takes it up.

Submission is the agent's act of asking for a price, and it is gated. The application must be in `DRAFT`, otherwise `ERR_APPLICATION_NOT_DRAFT`. The property must have a committed estimate — its `replacement_cost` must be greater than 0 — otherwise `ERR_REPLACEMENT_COST_MISSING`. The requested Coverage A must be at least the property's committed replacement cost, otherwise `ERR_COVERAGE_BELOW_REPLACEMENT_COST`. And a risk assessment must already exist for the application's property, otherwise `ERR_RISK_ASSESSMENT_NOT_FOUND`; when more than one risk assessment has been recorded against that property, the most recently created one (the highest by creation order) is the one whose figures feed the quote, and it is likewise the one consulted for the score-stage and wildfire checks at binding time. When these hold, the application advances from `DRAFT` to `SUBMITTED` and a quote is generated as a `BOUND_OFFER`; any prior `BOUND_OFFER` quote on the same application is marked `SUPERSEDED`, since a newer quote always supersedes the prior one. The application's `quoted_premium` is set to the new quote's `annual_premium`.

The quote names the `application_id` it prices and computes four read-only figures. The pre-endorsement annual figure, `base_premium`, is built in a pinned order. First a Coverage-A tier rate is selected by where the requested Coverage A falls: the rate is 0.0040 when the requested Coverage A is at least 0 and below 200,000; 0.0035 when it is at least 200,000 and below 400,000; and 0.0031 when it is 400,000 or more. The base figure is the requested Coverage A multiplied by that tier rate. Three zone multipliers are then applied multiplicatively. The wildfire multiplier is one plus five thousandths for each point by which the wildfire score exceeds 40, applying no surcharge at or below 40 — formally, it is one plus five thousandths times the greater of zero and the amount the wildfire score exceeds 40, using whichever of the property's wildfire score, provisional or final, is current at quote time. The flood multiplier depends on the flood zone: 1.0 for `X`, 1.2 for `A`, 1.35 for `AE`, and 1.6 for `VE`. The wind/hail multiplier depends on the tier: 1.0 for `TIER_1`, 1.18 for `TIER_2`, and 1.4 for `TIER_3`. Multiplying the base figure by all three yields the zoned figure. Finally a deductible credit is applied — a higher deductible lowers the premium: the zoned figure is multiplied by one minus the credit for the chosen deductible percent, where the credit is 0.0 at 1 percent, 0.05 at 2 percent, and 0.12 at 5 percent. That result, rounded half up to two decimal places, is the `base_premium`.

The quote's `endorsement_premium` is the sum of `premium_delta` across the endorsements that are in `PENDING` at quote time, each delta already rounded, with the sum itself rounded half up to two decimal places. The quote's `annual_premium` is the sum of the rounded `base_premium` and the rounded `endorsement_premium`, assembled in the per-component-then-sum order described in Section 2.7.

The quote also carries the dollar wind/hail deductible, `wind_hail_deductible_amount`. This is computed from the committed Coverage A — the requested Coverage A — before any premium credit is applied, so that the deductible credit inside the premium never feeds back into the deductible figure. The raw deductible is the requested Coverage A multiplied by the deductible percent divided by 100; the stored amount is the greater of that raw figure and a 2,500 dollar minimum floor, rounded half up to two decimal places. A quote begins life as a `BOUND_OFFER` and becomes `SUPERSEDED` once a newer quote is generated on the same application.

### 3.5. Endorsements: Widening and Narrowing Coverage

Alongside the base application, an agent can attach riders called endorsements, each naming the `application_id` it modifies. An endorsement has a `kind` — either `PERIL_ADD`, which widens coverage and carries a premium debit, or `EXCLUSION`, which narrows coverage and carries a premium credit — and a `peril_code`, one of `WATER_BACKUP`, `SCREENED_ENCLOSURE`, `ORDINANCE_LAW`, `EARTH_MOVEMENT`, or `MOLD`. A peril-add carries an additive `coverage_limit` (zero or greater); an exclusion carries no added limit, so its `coverage_limit` defaults to 0. A new endorsement is `DRAFT` with its `premium_delta` at 0.

An agent attaches a draft endorsement to bring it into play, moving it from `DRAFT` to `PENDING`. Attaching is allowed only when the endorsement is in `DRAFT`, otherwise `ERR_ENDORSEMENT_NOT_DRAFT`, and only while the parent application is still open — that is, in `DRAFT`, `SUBMITTED`, or `UNDER_REVIEW` — otherwise `ERR_APPLICATION_NOT_OPEN_FOR_ENDORSEMENT`. Attaching computes the signed `premium_delta`. For a peril-add, the delta is positive: the coverage limit multiplied by the per-peril rate — 0.004 for `WATER_BACKUP`, 0.003 for `SCREENED_ENCLOSURE`, 0.0025 for `ORDINANCE_LAW`, 0.006 for `EARTH_MOVEMENT`, and 0.005 for `MOLD` — rounded half up to two decimal places. For an exclusion, the delta is negative: the negation of a flat per-peril credit — 60 for `WATER_BACKUP`, 45 for `SCREENED_ENCLOSURE`, 80 for `ORDINANCE_LAW`, 140 for `EARTH_MOVEMENT`, and 70 for `MOLD` — with that credit rounded half up to two decimal places before negation.

Endorsements come to rest only as a consequence of what happens to their parent application. When an application is bound, every endorsement on it that is in `PENDING` advances to `APPLIED` as part of the binding cascade, and each applied endorsement posts to the new policy's ledger (detailed in Section 3.6). An applied peril-add or exclusion is the only kind that touches the policy's books. When an application is instead declined, every endorsement on it that is still in `DRAFT` or in `PENDING` is moved to `REJECTED`. An underwriter may also remove an endorsement that has already reached `APPLIED`, as a compensating amendment described in Section 3.7. The terminal resting states for an endorsement are `REJECTED` and `REMOVED`.

### 3.6. Underwriting Review and Binding

Underwriters are themselves provisioned by an administrator, who records each underwriter's `full_name` and the `authority_limit` — the maximum Coverage A that underwriter may bind without escalation, which must be a number strictly greater than 0 or the creation is rejected with `ERR_INVALID_REQUEST`. Once an application is `SUBMITTED`, it waits in a queue for an underwriter. An underwriter takes a submitted application under review, which is permitted only from `SUBMITTED`, otherwise `ERR_APPLICATION_NOT_SUBMITTED`; taking it sets the application's `assigned_underwriter_id` to the acting underwriter and moves it from `SUBMITTED` to `UNDER_REVIEW`. The assigned underwriter may release it back to the queue, returning it from `UNDER_REVIEW` to `SUBMITTED` and clearing `assigned_underwriter_id` to null; this is allowed only while the application is `UNDER_REVIEW` (otherwise `ERR_APPLICATION_NOT_UNDER_REVIEW`) and only by the assigned underwriter (otherwise `ERR_NOT_ASSIGNED_UNDERWRITER`).

Binding is the carrier's acceptance of the risk, moving the application from `UNDER_REVIEW` to `BOUND`. The underwriter supplies the policy's `effective_date` and `expiration_date` — both Unix epoch seconds, with the expiration strictly after the effective date — together with `expected_application_version` for the concurrency check. Binding is gated by a full underwriting panel, evaluated after the universal authentication, authorization, existence, and state gates. The application must be `UNDER_REVIEW`, otherwise `ERR_APPLICATION_NOT_UNDER_REVIEW`. The acting underwriter must be the one assigned, otherwise `ERR_NOT_ASSIGNED_UNDERWRITER` — this is the segregation of duties point, since the producer is an agent and the binder must be the assigned underwriter. There must be a `PASSED` inspection for the application's property, otherwise `ERR_INSPECTION_NOT_PASSED`. The property's risk assessment must have reached `FINAL` stage, otherwise `ERR_SCORE_NOT_FINAL`. The final wildfire score must be strictly less than 80 to be insurable; a score of 80 or higher declines the risk with `ERR_WILDFIRE_UNINSURABLE`, the boundary sitting exactly at 80. The requested Coverage A must be at most the acting underwriter's `authority_limit`, otherwise `ERR_AUTHORITY_LIMIT_EXCEEDED`. And `expected_application_version` must match the application's current `version`, otherwise `ERR_STALE_APPLICATION_VERSION`.

A successful bind sets the application to `BOUND` and increments the application's `version` by one. It then runs a cascade. First a policy is created in `PENDING_PAYMENT`, carrying the application's `property_id`, an `annual_premium` copied from the latest `BOUND_OFFER` quote's `annual_premium`, and a starting `premium_balance` of 0. Second, every endorsement on the application that is in `PENDING` transitions to `APPLIED`. Third, each newly applied endorsement posts to the new policy's ledger: a peril-add posts a DEBIT for its `premium_delta`, while an exclusion posts a CREDIT for the absolute value of its `premium_delta`; the policy's `premium_balance` is recomputed from the ledger after these postings. Each applied peril-add additionally raises the property's `total_insured_value` by its `coverage_limit`.

Declining is the alternative terminal outcome from review. The underwriter declines with a `reason`, which must be `WILDFIRE_UNINSURABLE` or `INSPECTION_FAILED`; declining is permitted only while the application is `UNDER_REVIEW` (otherwise `ERR_APPLICATION_NOT_UNDER_REVIEW`) and only by the assigned underwriter (otherwise `ERR_NOT_ASSIGNED_UNDERWRITER`). A decline moves the application to `DECLINED`, records the supplied reason in `decline_reason`, and rejects every endorsement on the application that is still in `DRAFT` or `PENDING`, moving each to `REJECTED`. Both `BOUND` and `DECLINED` are terminal for an application.

### 3.7. Paying, Activating, and Servicing the Policy

A bound policy names the `application_id` it came from and the insured `property_id`, and it sits in `PENDING_PAYMENT` until the agent settles the binding amount. Payment is the agent's act and drives the policy forward. The agent records a payment naming the `policy_id`, a `purpose` of either `BINDING` or `REINSTATEMENT`, and an `amount` (which must be positive). A payment is recorded only on success and rests in `SETTLED`.

A binding payment activates the policy, moving it from `PENDING_PAYMENT` to `ACTIVE`. It is gated: the policy must be `PENDING_PAYMENT`, otherwise `ERR_POLICY_NOT_PENDING_PAYMENT`; the tendered `amount` must equal the policy's `annual_premium`, otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`; and no other `ACTIVE` or `REINSTATED` policy may already cover the same `property_id` over an overlapping coverage period, otherwise `ERR_COVERAGE_PERIOD_OVERLAP`. Coverage periods run from `effective_date` to `expiration_date` as a closed interval inclusive of both ends, and two such intervals overlap when they share any instant. On success the policy becomes `ACTIVE` and the system posts a DEBIT to the ledger for the `annual_premium` as the binding premium, recomputing `premium_balance`.

An underwriter may lapse an active policy. Lapsing requires `expected_policy_version` and is permitted from `ACTIVE` or from `REINSTATED` — in either case a state outside this pair yields `ERR_POLICY_NOT_ACTIVE`, and a version mismatch yields `ERR_STALE_POLICY_VERSION`. A lapse moves the policy to `LAPSED`, increases its `lapse_count` by one, increments the policy's `version` by one for that state mutation, and posts a CREDIT to the ledger for the entire current `premium_balance` as a lapse write-off, so that `premium_balance` returns to 0; because the write-off recomputes `premium_balance`, that recomputation is itself a mutation under §2.4 and increments `version` once more, so a lapse advances `version` by two in total.

A lapsed policy can be reinstated by the agent through a reinstatement payment, which moves the policy from `LAPSED` to `REINSTATED`. It is gated: the policy must be `LAPSED`, otherwise `ERR_POLICY_NOT_LAPSED`; the policy's `lapse_count` must be at most 2, otherwise `ERR_REINSTATEMENT_LIMIT_EXCEEDED`, so that a third lapse can never be reinstated; and the tendered `amount` must equal the policy's `annual_premium` plus a flat reinstatement fee of 250 dollars, otherwise `ERR_PAYMENT_AMOUNT_MISMATCH`. On success the policy becomes `REINSTATED`, and the system posts two DEBITs to the ledger — one for the `annual_premium` as a re-billed binding premium and one for the 250 dollar reinstatement fee — recomputing `premium_balance`. A reinstated policy can itself later be lapsed again under the same lapse rules.

An underwriter can cancel a policy outright. Cancellation is permitted while the policy is `ACTIVE`, `REINSTATED`, or `LAPSED`, otherwise `ERR_POLICY_NOT_CANCELLABLE`, and it moves the policy to the terminal `CANCELLED` state.

Finally, an underwriter may remove an endorsement that has been applied to a bound policy, as a compensating amendment. Removal is allowed only when the endorsement is `APPLIED`, otherwise `ERR_ENDORSEMENT_NOT_APPLIED`, and only while the application's policy is in `PENDING_PAYMENT`, `ACTIVE`, or `REINSTATED`, otherwise `ERR_POLICY_NOT_AMENDABLE`. Removing an endorsement moves it to `REMOVED` and posts the exact reversal of its original ledger entry: for a removed peril-add the reversal is a CREDIT for its `premium_delta`, and for a removed exclusion the reversal is a DEBIT for the absolute value of its `premium_delta`; `premium_balance` is recomputed afterward. Removing a peril-add also lowers the property's `total_insured_value` by that endorsement's `coverage_limit`. Because the reversal exactly offsets the original posting, the balance and the total insured value land precisely where they would have been had the endorsement never applied.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`. Operations that modify or transition an existing resource — including the various submit, review, bind, decline, complete, reschedule, attach, remove, lapse, and cancel actions — return `200 OK`. Recording a payment creates a new Payment resource and therefore returns `201 Created`, even though it also drives a policy transition.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/underwriters` | Create an Underwriter | Admin |
| POST | `/properties` | Create a Property | Agent |
| GET | `/properties` | List Properties (ARCHIVED excluded unless include_archived=true) | Admin, Agent, Underwriter |
| GET | `/properties/{id}` | Get a Property | Admin, Agent, Underwriter |
| POST | `/properties/{id}/estimate-replacement-cost` | Compute and commit a replacement-cost estimate under the chosen variant | Agent |
| POST | `/risk-assessments` | Create a RiskAssessment and compute the provisional wildfire score and wind/hail tier | Underwriter |
| GET | `/risk-assessments` | List RiskAssessments (filter by property_id) | Admin, Agent, Underwriter |
| GET | `/risk-assessments/{id}` | Get a RiskAssessment | Admin, Agent, Underwriter |
| POST | `/inspectors` | Create an Inspector | Admin |
| POST | `/inspections` | Schedule a four-point Inspection | Underwriter |
| GET | `/inspections` | List Inspections (filter by property_id and/or inspector_id) | Admin, Agent, Underwriter, Inspector |
| GET | `/inspections/{id}` | Get an Inspection | Admin, Agent, Underwriter, Inspector |
| POST | `/inspections/{id}/complete` | Submit four-point results; auto-resolves PASSED or FAILED | Inspector |
| POST | `/inspections/{id}/reschedule` | Reschedule a FAILED inspection | Inspector |
| POST | `/applications` | Create a DRAFT Application | Agent |
| GET | `/applications` | List Applications (filter by property_id, agent_id, assigned_underwriter_id) | Admin, Agent, Underwriter |
| GET | `/applications/{id}` | Get an Application | Admin, Agent, Underwriter |
| POST | `/applications/{id}/submit` | Submit a DRAFT application; generates a Quote | Agent |
| POST | `/applications/{id}/take-review` | Take a SUBMITTED application under review | Underwriter |
| POST | `/applications/{id}/return-to-queue` | Return the application to the submitted queue | Underwriter |
| POST | `/applications/{id}/bind` | Bind the application into a Policy | Underwriter |
| POST | `/applications/{id}/decline` | Decline the application under review | Underwriter |
| POST | `/endorsements` | Create a DRAFT Endorsement on an application | Agent |
| GET | `/endorsements` | List Endorsements (filter by application_id) | Admin, Agent, Underwriter |
| GET | `/endorsements/{id}` | Get an Endorsement | Admin, Agent, Underwriter |
| POST | `/endorsements/{id}/attach` | Attach a DRAFT endorsement; computes premium_delta | Agent |
| POST | `/endorsements/{id}/remove` | Remove an APPLIED endorsement (compensating reversal) | Underwriter |
| GET | `/quotes` | List Quotes (filter by application_id) | Admin, Agent, Underwriter |
| GET | `/quotes/{id}` | Get a Quote | Admin, Agent, Underwriter |
| GET | `/policies` | List Policies (filter by application_id and/or property_id) | Admin, Agent, Underwriter |
| GET | `/policies/{id}` | Get a Policy | Admin, Agent, Underwriter |
| POST | `/policies/{id}/lapse` | Lapse an ACTIVE or REINSTATED policy | Underwriter |
| POST | `/policies/{id}/cancel` | Cancel a policy | Underwriter |
| POST | `/payments` | Record a binding or reinstatement payment | Agent |
| GET | `/payments` | List Payments (filter by policy_id) | Admin, Agent, Underwriter |
| GET | `/payments/{id}` | Get a Payment | Admin, Agent, Underwriter |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_PROPERTY_NOT_FOUND` | 404 Not Found |
| `ERR_RISK_ASSESSMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTOR_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_ENDORSEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_QUOTE_NOT_FOUND` | 404 Not Found |
| `ERR_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_UNDERWRITER_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_DRAFT` | 409 Conflict |
| `ERR_APPLICATION_NOT_SUBMITTED` | 409 Conflict |
| `ERR_APPLICATION_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_NOT_ASSIGNED_UNDERWRITER` | 403 Forbidden |
| `ERR_ENDORSEMENT_NOT_DRAFT` | 409 Conflict |
| `ERR_ENDORSEMENT_NOT_APPLIED` | 409 Conflict |
| `ERR_APPLICATION_NOT_OPEN_FOR_ENDORSEMENT` | 409 Conflict |
| `ERR_POLICY_NOT_AMENDABLE` | 409 Conflict |
| `ERR_INSPECTION_NOT_SCHEDULED` | 409 Conflict |
| `ERR_INSPECTION_NOT_FAILED` | 409 Conflict |
| `ERR_POLICY_NOT_PENDING_PAYMENT` | 409 Conflict |
| `ERR_POLICY_NOT_ACTIVE` | 409 Conflict |
| `ERR_POLICY_NOT_LAPSED` | 409 Conflict |
| `ERR_POLICY_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_REPLACEMENT_COST_MISSING` | 409 Conflict |
| `ERR_COVERAGE_BELOW_REPLACEMENT_COST` | 422 Unprocessable Entity |
| `ERR_INSPECTION_NOT_PASSED` | 409 Conflict |
| `ERR_SCORE_NOT_FINAL` | 409 Conflict |
| `ERR_WILDFIRE_UNINSURABLE` | 422 Unprocessable Entity |
| `ERR_AUTHORITY_LIMIT_EXCEEDED` | 403 Forbidden |
| `ERR_COVERAGE_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_REINSTATEMENT_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INSPECTION_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_APPLICATION_VERSION` | 412 Precondition Failed |
| `ERR_STALE_POLICY_VERSION` | 412 Precondition Failed |
