# Airport Wildlife Hazard API — Product Requirements Document

## 1. Introduction

Managing wildlife strikes at a commercial airport is a heavily regulated, multi-actor discipline. Field biologists log strikes and run dispersal operations, air-traffic controllers decide when runways must close for carcass recovery or hazard sweeps, federal and state regulators issue depredation permits and sign off on the airport's annual wildlife hazard plan, and an administrative operator maintains the reference rosters that tie it all together. A single mis-step — a lethal take logged against the wrong permit, a hazard posture that does not reflect last night's strike spike, a mitigation action started while the airport sits at `CRITICAL` — can cascade into enforcement action, an unsafe runway, or a failed audit.

This document specifies the Airport Wildlife Hazard API, the system of record for the airport's wildlife hazard management program. It covers the full program lifecycle: strike reporting and carcass identification, habitat assessment and the mitigation actions that flow from it, dispersal activity and the take-permit accounting that bounds it, hazard-level advisories and the runway closures they sometimes require, and the annual plan and training currency that close the regulatory loop. The API is mounted under `/wildlife`.

The design is deliberately conservative: many state transitions are gated by segregation-of-duties checks (the person who reported a strike cannot be the one who confirms it), several write paths are protected by optimistic concurrency on the parent `Airport` aggregate, and a small number of thresholds — most visibly the trailing twelve-month strike counts — drive an automatic recomputation of the airport's `current_hazard_level`, which in turn gates whole classes of operations.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two HTTP headers identifying the caller: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role value outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted to invoke the target endpoint per the RBAC matrix is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Four roles are defined, with exact spellings as follows:

- `AirportAdmin` — an administrative operator who onboards airports, species, biologists, ATC controllers, and regulator agents, and who alone can drive the logical clock. When `X-User-Role` is `AirportAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.
- `WildlifeBiologist` — a field biologist who logs strike reports, identifies carcasses, performs dispersals, proposes and works mitigation actions, issues operational advisories, and authors annual plans. When `X-User-Role` is `WildlifeBiologist`, `X-User-ID` is the `id` of the acting `WildlifeBiologist`; ownership checks on any resource that references a `WildlifeBiologist` (for example `reporter_biologist_id`, `proposed_by_biologist_id`, `performed_by_biologist_id`, `requested_by_biologist_id`, `issued_by_biologist_id`) compare the resource's foreign-key field to `X-User-ID`.
- `ATCController` — a tower controller who authorizes, denies, or releases runway closures at their own airport. When `X-User-Role` is `ATCController`, `X-User-ID` is the `id` of the acting `ATCController`; the cross-facility check on closure authorization compares the controller's `airport_id` to the closure's `airport_id`.
- `RegulatorAgent` — a USFWS, USDA Wildlife Services, or state DNR agent who issues take permits, files annual depredation reports, approves or returns annual plans, and revokes training credentials. When `X-User-Role` is `RegulatorAgent`, `X-User-ID` is the `id` of the acting `RegulatorAgent`; the revocation precondition compares the acting agent's `agency` to the permit's issuing agency.

Authentication itself does not resolve `X-User-ID` against any roster: ownership checks compare the raw header value to the resource's foreign-key field, and seniority checks look the value up directly, so an `X-User-ID` matching no persisted biologist is simply treated as non-senior (and analogously fails the cross-facility or agency-match checks that require a persisted controller or regulator record).

The full per-endpoint authorization matrix appears in §4.

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

All list endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum of 100; `offset` defaults to 0 and must not be negative. A non-integer or out-of-range value for either parameter is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List results are always sorted by `created_at` ascending (ties broken by insertion order) unless otherwise noted. Every list response's `meta` block reports `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties, Identifiers, and Timestamps

Every persisted entity carries an `id` that is a server-minted UUID with no type prefix; the identifier appears in URL path positions as a bare `{id}`. Unless stated otherwise, every entity also carries `created_at` and `updated_at` timestamps in ISO 8601 UTC with three fractional digits, and a `version` integer that starts at 1 and is incremented by 1 on every state transition or other mutation of that resource. All entities in this domain — `Airport`, `WildlifeBiologist`, `ATCController`, `RegulatorAgent`, `Species`, `WildlifeStrikeReport`, `CarcassRecord`, `HabitatAssessment`, `MitigationAction`, `DispersalActivity`, `TakePermit`, `OperationalAdvisory`, `RunwayClosure`, `AnnualPlan`, and `TrainingRecord` — carry the full set of common fields.

### 2.5. Nested Resource Retrieval and Reference Resolution

Where an endpoint's path is nested (for example, carcass records under a strike report, or mitigation actions under a habitat assessment), every path-templated identifier is resolved left-to-right: the leftmost identifier is validated first, then the next, and so on. A path identifier that does not resolve to an existing record is rejected with `ERR_NOT_FOUND` (HTTP 404). Separately, every foreign key supplied in a request body must reference an existing record of the correct entity type; violations are rejected with `ERR_FK_NOT_FOUND` (HTTP 422). The reference-resolution check runs after authentication and role checks but before any state-machine or business-rule evaluation.

Two further generic 400-level rejections apply across all write endpoints. A request that omits a required field, or supplies a value that falls outside the field's declared constraint range (a `body_mass_g` of zero, an `attractiveness_score` of eleven, an `annual_plan_cycle_year` outside 2000–2100, a malformed `runway_designator`, and so on), is rejected with `ERR_INVALID_REQUEST` (HTTP 400). A request that supplies an enum field with a value outside the declared set (an unrecognized `damage_class`, `phase_of_flight`, `guild`, `risk_tier`, `action_type`, `method`, `habitat_feature`, `disposal_method`, `identification_method`, `reason_code`, `reason`, `agency`, or `hazard_level`) is rejected with `ERR_INVALID_ENUM` (HTTP 400); the same rule applies to enum-valued list-filter query parameters such as `status` or `damage_class`. Uniqueness violations on the unique scalar fields declared in §3 — an airport's `icao_code`, a species' `common_name`, a biologist's `certification_id`, a regulator's `badge_number`, a permit's `permit_number` — are likewise rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.6. Validation Priority Ordering

When a single request could fail more than one validation, the checks run in a fixed order so that the error surfaced is deterministic. The order is: authentication (`ERR_UNAUTHENTICATED`) first, then role authorization (`ERR_UNAUTHORIZED`), then path-identifier resolution (`ERR_NOT_FOUND`), then body foreign-key resolution (`ERR_FK_NOT_FOUND`), then state-machine legality (`ERR_INVALID_STATE`), then the hazard-posture gate (`ERR_HAZARD_CRITICAL_BLOCK`), then segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), then the senior-biologist requirement (`ERR_SENIOR_REQUIRED`), then temporal-window validity (`ERR_INVALID_WINDOW`), then closure-overlap (`ERR_CLOSURE_CONFLICT`), then take-permit presence (`ERR_TAKE_PERMIT_REQUIRED`), then plan-year uniqueness (`ERR_PLAN_DUPLICATE_YEAR`), then take-budget overrun (`ERR_TAKE_BUDGET_EXCEEDED`), then the federal-permit requirement (`ERR_FEDERAL_PERMIT_REQUIRED`), then closure duration (`ERR_CLOSURE_DURATION_EXCEEDED`), then identification-method readiness (`ERR_ID_METHOD_PENDING`), then the mandatory-mitigation rule (`ERR_MITIGATION_REQUIRED`), then permit-window validity (`ERR_PERMIT_OUTSIDE_WINDOW`), then the cross-facility check (`ERR_CROSS_FACILITY_FORBIDDEN`), and finally the optimistic-concurrency check (`ERR_STALE_VERSION`). A request failing several of these surfaces only the earliest error in this order. Generic request-shape validation (`ERR_INVALID_REQUEST` and `ERR_INVALID_ENUM` on the documented payload fields) is not a business rule and is therefore not listed above: it runs after path-identifier resolution and before body foreign-key resolution. Fields that a specific transition makes conditionally required — `confirmation_notes` on strike confirmation, `override_note` on a sub-threshold mitigation approval, `effectiveness_rating` on mitigation completion — are validated only after that transition's state, segregation-of-duties, and seniority checks have passed.

### 2.7. Optimistic Concurrency Control on the Airport Aggregate

Two write endpoints require the caller to declare the version of the parent `Airport` it last observed. Both advisory activation and annual-plan publication accept a required `expected_airport_version` field in the request body. If the supplied value does not match the `Airport` record's current `version`, the write is rejected with `ERR_STALE_VERSION` (HTTP 412). A missing or non-integer `expected_airport_version` is rejected with `ERR_INVALID_REQUEST` (HTTP 400) before any state-machine evaluation. This protects against the case where a competing advisory was just activated, or a competing plan was just published, and the client's view of the airport's hazard posture is therefore stale. Endpoints not listed here do not take a version field.

### 2.8. Hazard Posture as a System-Wide Gate

Every `Airport` carries a derived `current_hazard_level`, one of `LOW`, `ELEVATED`, `HIGH`, or `CRITICAL`, which is recomputed from recent confirmed strikes, active advisories, and overdue mitigations (see §3.5). A `CRITICAL` posture is a hard stop on four operations across the system: submitting a new strike report from `DRAFT` to `SUBMITTED`, starting work on an approved mitigation action, publishing an approved annual plan, and releasing an active runway closure back to operations. All four reject with `ERR_HAZARD_CRITICAL_BLOCK` (HTTP 409).

### 2.9. Segregation of Duties and Seniority

Many review and approval transitions enforce two orthogonal checks. Segregation of duties forbids the same individual who performed the prior step — the strike reporter, the mitigation proposer, the dispersal performer, the carcass identifier — from performing the follow-up review, approval, confirm, complete, dispute, or resolve action; violations are rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Seniority requires that certain actions — confirming a strike for a `HIGH` or `CRITICAL` risk-tier species, identifying or disputing or resolving a carcass ID, approving or rejecting or completing a mitigation action, closing a dispersal, activating an operational advisory — be performed by a biologist whose `is_senior` is `true`; violations are rejected with `ERR_SENIOR_REQUIRED` (HTTP 403). For strike-confirm and carcass-identify, the seniority requirement is waived when the species involved has a `risk_tier` of `LOW` or `MEDIUM`.

### 2.10. Logical Clock and Time-Driven Transitions

The server maintains a logical clock that is independent of wall time and defaults to `2026-08-01T00:00:00Z` before any operator sets it. An admin-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant — any ISO 8601 instant is accepted, with no requirement that it be later than the current value — and returns the new value under `current_utc` in the response `data`. Several system transitions are evaluated against this clock rather than wall time: take permits move from `ISSUED` to `ACTIVE` when the clock reaches `valid_from`, and from `ACTIVE` (or a never-activated `ISSUED`) to `EXPIRED` when the clock passes `valid_to`; advisories move from `ACTIVE` to `EXPIRED` when the clock passes `effective_to`; runway closures move from `AUTHORIZED` to `ACTIVE` when the clock reaches `closure_start`; training records move from `VALID` to `EXPIRING_SOON` once the clock's date reaches the date thirty days before `expires_at` and from either state to `EXPIRED` once past `expires_at`. Setting the clock triggers evaluation of every such pending transition, and the same evaluation also runs at the start of every request, so pending transitions fire on ordinary traffic. The logical clock is the system's only time source: every server-stamped timestamp — the envelope `api_request_timestamp`, `created_at`/`updated_at`, and workflow stamps such as `identified_at`, `completed_at`, `submitted_at`, `published_at`, and `actual_released_at` — is taken from it rather than from wall time.

## 3. Business Logic & Workflows

### 3.1. Program Onboarding and Reference Data

Before any field work can be recorded, an `AirportAdmin` seeds the program's reference data. Each `Airport` is registered with its ICAO four-letter code in `icao_code` (must match the four-uppercase-letter pattern and is unique and immutable once set), a human-readable `name`, and an `annual_plan_cycle_year` between 2000 and 2100 that anchors the planning calendar. On creation the airport's `current_hazard_level` starts at `LOW`, both `strikes_trailing_12m` and `strikes_trailing_12m_high_risk` start at zero, and `hazard_level_updated_at` is unset until the first recompute.

Species are registered with a unique `common_name`, a `scientific_name`, a functional `guild` drawn from `RAPTOR`, `WATERFOWL`, `GULL`, `SONGBIRD`, `BAT`, `MAMMAL`, `REPTILE`, or `OTHER`, a regulatory `risk_tier` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL`, a `body_mass_g` strictly greater than zero that feeds kinetic-energy scoring, and an `is_protected_federally` flag that defaults to `false` and, when `true`, makes any lethal take of that species contingent on a federal USFWS-issued permit. The biologist roster is registered with `full_name`, a unique `certification_id`, the home `airport_id`, an `is_senior` flag that defaults to `false` and gates the senior-only sign-off steps throughout the program, and an `active` flag that defaults to `true`. Tower controllers are registered with `full_name`, a `facility_id`, and the `airport_id` of their tower; their `active` flag also defaults to `true`. Regulator agents are registered with `full_name`, an `agency` of `USFWS`, `USDA_WS`, or `STATE_DNR`, and a unique `badge_number`. The reference-data list views support equality filters: airports by `icao_code` and `current_hazard_level`, species by `guild` and `risk_tier`, biologists by `airport_id`, `is_senior`, and `active`, and ATC controllers by `airport_id`.

### 3.2. Strike Reporting and Carcass Identification

When a strike occurs, a `WildlifeBiologist` logs a `WildlifeStrikeReport` carrying the `airport_id`, the `reporter_biologist_id` (which must equal the acting caller; a mismatch is rejected with `ERR_UNAUTHORIZED` (HTTP 403)), the `strike_at` UTC timestamp, the `runway_designator` (matching a two-digit runway number optionally suffixed with L, R, or C — e.g., `09L` or `27R`), the `aircraft_registration`, a best-known `species_id` (which may reference an UNKNOWN-species stub when the species is not yet identified), the `damage_class` (one of `NONE`, `MINOR`, `MEDIUM`, `SUBSTANTIAL`, `DESTROYED`, `UNKNOWN`), the `phase_of_flight` (one of `TAKEOFF`, `CLIMB`, `CRUISE`, `DESCENT`, `APPROACH`, `LANDING`, `TAXI`, `PARKED`), the `altitude_ft_agl` at zero or greater, the `strike_count_animals` at one or greater, and a `carcass_present` flag. New reports enter with their `status` field set to `DRAFT`, with `confirmed_by_biologist_id` and `confirmation_notes` null; the create call also accepts an optional `confirmation_notes`. The strike-report list view supports filtering by `airport_id`, `reporter_biologist_id`, `confirmed_by_biologist_id`, `status`, `damage_class`, and `species_id`, as well as by time range via `strike_after` and `strike_before` bounds on the `strike_at` field, both bounds inclusive.

Submitting a draft transitions it `DRAFT → SUBMITTED` and bumps the report's `version`. Submission is blocked outright while the airport is at `CRITICAL` hazard, surfacing `ERR_HAZARD_CRITICAL_BLOCK`. A reporter who wants to retract a submission before anyone has picked it up can return the report from `SUBMITTED` to `DRAFT`; this self-service transition is only available to the original reporter, and attempts by anyone else are rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Review begins when a *different* biologist begins review, moving the report `SUBMITTED → UNDER_REVIEW`; the segregation-of-duties check rejects the reporter attempting to review their own report with `ERR_SEGREGATION_OF_DUTIES`. From `UNDER_REVIEW` the reviewer has three options. Confirming the strike (`UNDER_REVIEW → CONFIRMED`) requires non-empty `confirmation_notes`, requires the acting biologist to be different from the reporter, and requires either that the acting biologist be senior or that the species' `risk_tier` be `LOW` or `MEDIUM`; on success the server stamps `confirmed_by_biologist_id` with the acting biologist's `id`, recomputes the airport's trailing-twelve-month strike counts, recomputes the airport's `current_hazard_level`, and — if `carcass_present` is `true` and no `CarcassRecord` yet exists for this strike — auto-creates a `CarcassRecord` in `COLLECTED` with `species_id_at_collection` set to the strike's `species_id` and its `identification_method`, `disposal_method`, `species_id_final`, `identified_by_biologist_id`, and `identified_at` unset. Rejecting the strike (`UNDER_REVIEW → REJECTED`) requires only the segregation-of-duties check.

A `CarcassRecord` may also be created manually under a strike report — regardless of the strike's status or `carcass_present` flag, and even when another carcass record already exists for it — supplying the parent `strike_report_id`, the `species_id_at_collection`, an `identification_method` of `VISUAL`, `DNA`, `FEATHER_SNARGE`, `MORPHOLOGY`, or `PENDING`, and a `disposal_method` of `BURIED`, `INCINERATED`, `ARCHIVED`, or `RELEASED_TO_AGENCY`. The record's `identification_status` field tracks where it sits in the identification lifecycle and starts at `COLLECTED`. The carcass-record list view supports filtering by `strike_report_id`, `identification_status`, `species_id_at_collection`, `species_id_final`, and `identified_by_biologist_id`. Sending to the lab moves a `COLLECTED` record to `PENDING_ID` and is only allowed when the `identification_method` is something other than `PENDING`; an attempt to send a record whose method is `PENDING` is rejected with `ERR_INVALID_STATE` (HTTP 409). Identification can happen directly from `COLLECTED` or from `PENDING_ID`, and transitions the record to `IDENTIFIED`; the request supplies `species_id_final` and may optionally supply a replacement `identification_method`, which is stored when present, and on success the server sets `species_id_final`, `identified_by_biologist_id`, and `identified_at`. The acting biologist must be senior unless the parent strike's species `risk_tier` is `LOW` or `MEDIUM`. Identification is forbidden while `identification_method` is still `PENDING` and surfaces `ERR_ID_METHOD_PENDING`; a `PENDING` value supplied in the identify request itself is rejected with the same error. When the final species differs from the parent strike's `species_id`, the parent strike report is cascaded to `AMENDED` automatically, its `species_id` is updated to match the new finding, and the airport's trailing strike counts and `current_hazard_level` are recomputed.

A senior biologist other than the one who recorded the identification may dispute it, moving the record `IDENTIFIED → DISPUTED`. Resolution moves a `DISPUTED` record to `RESOLVED`, again by a senior biologist other than the original identifier; resolution supplies a final `species_id_final` and leaves `identified_by_biologist_id` and `identified_at` unchanged, and if that final species differs from the parent strike's `species_id`, the parent is again cascaded to `AMENDED` with its `species_id` updated, and the airport's trailing strike counts and `current_hazard_level` are recomputed.

### 3.3. Habitat Assessment and Mitigation

Biologists periodically assess habitat features that attract wildlife. Creating a `HabitatAssessment` records the `airport_id`, the `assessed_by_biologist_id`, the `assessed_at` timestamp, the `habitat_feature` observed (one of `STANDING_WATER`, `VEGETATION_TALL`, `GRASSLAND`, `WASTE_SITE`, `RODENT_PREY_BASE`, `NESTING_STRUCTURE`, `FOOD_SOURCE`, `ROOSTING`), an `attractiveness_score` from 1 to 10, and a `severity_score` from 1 to 10. The server immediately computes `composite_score` as the product of the two scores, an integer in the range 1 to 100. The assessment list view supports filtering by `airport_id`, `assessed_by_biologist_id`, and `habitat_feature`, and a `min_composite_score` filter restricts results to assessments at or above a supplied composite threshold. An assessment whose `composite_score` is at least 60 — the mandatory-mitigation threshold — cannot be considered addressed until at least one `MitigationAction` in a status other than `REJECTED` exists under it; an assessment that would remain in breach of this rule at creation time surfaces `ERR_MITIGATION_REQUIRED`.

Under each assessment, biologists propose mitigation actions. Proposing one supplies the parent `habitat_assessment_id` (in the nested path), an `action_type` of `DRAINAGE`, `MOWING`, `FENCING`, `HABITAT_REMOVAL`, `DETERRENT`, `EXCLUSION`, or `PREY_REDUCTION`, the `proposed_by_biologist_id`, and a `target_completion_date` in ISO `YYYY-MM-DD` form. New actions enter with their `status` field set to `PROPOSED`. The mitigation-action list view supports filtering by `habitat_assessment_id`, `status`, `proposed_by_biologist_id`, and `reviewed_by_biologist_id`.

Approval moves a `PROPOSED` action to `APPROVED` and is restricted to a senior biologist other than the proposer; the reviewer must either confirm that the parent assessment's `composite_score` is at least the mandatory threshold of 60 or document an explicit override by supplying a non-blank `override_note` string in the approve request body — a sub-threshold approval submitted without one is rejected with `ERR_INVALID_REQUEST`. Approval stamps `reviewed_by_biologist_id`. Rejection also requires a senior biologist other than the proposer and moves `PROPOSED → REJECTED`. The proposer alone may cancel their own `PROPOSED` action (`PROPOSED → CANCELLED`); attempts by anyone else are rejected with `ERR_UNAUTHORIZED` (HTTP 403). Starting work moves `APPROVED → IN_PROGRESS` and is blocked while the airport is at `CRITICAL`. Verification moves `IN_PROGRESS → VERIFIED` and again must be performed by someone other than the proposer. Completion moves `VERIFIED → COMPLETED`, requires a senior biologist other than the proposer, and requires an `effectiveness_rating` integer from 1 to 5; on success the server stamps `completed_at` and recomputes the airport's `current_hazard_level`.

### 3.4. Dispersal Activity and Take-Permit Accounting

Dispersal events are the field work of actually moving wildlife off the airfield. Logging a `DispersalActivity` records the `airport_id`, the `performed_by_biologist_id`, the `performed_at` timestamp, the `method` (one of `PYROTECHNICS`, `DISTRESS_CALLS`, `VEHICULAR`, `LASER`, `DOG`, `FALCONRY`, `LETHAL_AMMO`), the target `species_id`, the `animals_dispersed` count (zero or more), the `animals_taken_lethal` count (zero or more), and optionally a `take_permit_id`. The permit reference is mandatory whenever `animals_taken_lethal` is greater than zero or `method` is `LETHAL_AMMO`; in those cases the referenced permit must be in `ACTIVE` status, must cover the same airport and species, and the proposed take must fit within the permit's remaining authorized budget. Lethal-logging failures surface `ERR_TAKE_PERMIT_REQUIRED` (HTTP 422). Independently, the `performed_at` timestamp must fall within the permit's `valid_from` to `valid_to` window inclusive, compared at calendar-date granularity (the calendar date of `performed_at` must lie between the two permit dates); violations surface `ERR_PERMIT_OUTSIDE_WINDOW`. And if the target species is federally protected (`is_protected_federally` is `true`) and the method is `LETHAL_AMMO`, the referenced permit must have been issued by a regulator whose `agency` is `USFWS`; violations surface `ERR_FEDERAL_PERMIT_REQUIRED`. New dispersals enter in `LOGGED`. The dispersal list view supports filtering by `airport_id`, `performed_by_biologist_id`, `status`, `method`, `species_id`, and `take_permit_id`, as well as by time range via `performed_after` and `performed_before` bounds on the `performed_at` field, both bounds inclusive.

A dispersal is reviewed by a biologist other than the performer (`LOGGED → REVIEWED`). Closure from `REVIEWED` to `CLOSED` requires a senior biologist; if `animals_taken_lethal` is greater than zero, the referenced permit must still be `ACTIVE` and `take_consumed` plus the proposed `animals_taken_lethal` must not exceed the permit's `authorized_take_total` — a closure that would overrun the budget is rejected with `ERR_TAKE_BUDGET_EXCEEDED` (HTTP 422). Successful closure with lethal take recomputes the permit's `take_consumed`.

Take permits are issued by a `RegulatorAgent` and carry the `airport_id`, the `species_id`, the `issued_by_regulator_id`, a unique `permit_number`, an `authorized_take_total` of at least one, and a validity window from `valid_from` to `valid_to` inclusive, both supplied as ISO `YYYY-MM-DD` dates with no ordering constraint enforced between them at issuance. New permits enter in `ISSUED` with `take_consumed` at zero and `annual_report_submitted` as `false`. The system transitions a permit `ISSUED → ACTIVE` when the logical clock reaches `valid_from`. A permit in `ACTIVE` moves to `EXHAUSTED` when `take_consumed` reaches `authorized_take_total` after a dispersal closure, and moves to `EXPIRED` when the clock passes `valid_to`; a permit that was never activated also moves `ISSUED → EXPIRED` under the same clock rule. The permit list view supports filtering by `airport_id`, `species_id`, `status`, and `issued_by_regulator_id`. A per-permit take-preview returns `projected_take_consumed` — the lethal take summed across the permit's `CLOSED` and `REVIEWED` dispersals — and `projected_remaining`, the authorized total minus that projection.

A regulator closes a permit by submitting the annual depredation report, which supplies a `report_body` and transitions the permit from `ACTIVE` or `EXHAUSTED` to `CLOSED`; on success `annual_report_submitted` flips to `true`. The submission is only accepted when the report reconciles: the permit's `take_consumed` must equal the sum of `animals_taken_lethal` across every `CLOSED` dispersal referencing the permit, and a non-reconciling submission is rejected with `ERR_TAKE_PERMIT_REQUIRED` (HTTP 422). A regulator may also revoke an `ACTIVE` permit; revocation is restricted to a regulator whose `agency` matches the issuing agency (a mismatch is rejected with `ERR_UNAUTHORIZED` (HTTP 403)), and on revocation every still-`LOGGED` dispersal referencing the permit is cascaded to `FLAGGED` so the field team knows the authorization underpinning it is gone. A `FLAGGED` dispersal can still be closed by a senior biologist — the take physically happened and must be counted — but such closure does not consume further budget and requires the permit to be in `REVOKED`; a closure attempt whose permit is not yet `REVOKED` surfaces `ERR_TAKE_PERMIT_REQUIRED` (HTTP 422).

### 3.5. Hazard Assessment, Advisories, and Runway Closures

The airport's `current_hazard_level` is a derived posture recomputed on several triggers: a strike confirmation, an advisory activation, supersession, or expiry, a mitigation completion, or a runway release. The recompute proceeds bottom-up. First, the trailing-window strike counts set a base level: if `strikes_trailing_12m_high_risk` is at least 2, the base is `CRITICAL`; otherwise if it is exactly 1, the base is `HIGH`; otherwise if `strikes_trailing_12m` is at least 10, the base is `HIGH`; otherwise if it is at least 5, the base is `ELEVATED`; otherwise the base is `LOW`. Second, any `ACTIVE` advisory on the airport can only raise the level: if any active advisory declares a hazard level more severe than the current base, the level is promoted to that advisory's level, with `CRITICAL` outranking `HIGH` outranking `ELEVATED` outranking `LOW`. Third, if at least one mitigation action is in `IN_PROGRESS` or `VERIFIED` with a `target_completion_date` in the past and the level is still `LOW`, the level is promoted to `ELEVATED`. The result is persisted to `current_hazard_level` and `hazard_level_updated_at` is stamped with the current time. A separate what-if projection endpoint requires an `as_of` query parameter and evaluates the same level algorithm against it without persisting anything, with one difference: its trailing window is prospective, counting `CONFIRMED` strikes with `strike_at` strictly after `as_of` minus three hundred sixty-five days and no later than `as_of` (advisory and overdue-mitigation inputs reflect current record state, the overdue comparison using the `as_of` date). The response carries `projected_hazard_level`, `projected_strikes_trailing_12m`, and `projected_strikes_trailing_12m_high_risk`.

The trailing-window counts themselves are a rolling twelve-month window over the airport's `CONFIRMED` strikes. `strikes_trailing_12m` counts every `CONFIRMED` strike at the airport with `strike_at` no earlier than three hundred sixty-five days before now; a strike falling exactly on the window boundary is included. `strikes_trailing_12m_high_risk` counts the same window but restricted to strikes whose `damage_class` is `SUBSTANTIAL` or `DESTROYED`. Both counts are exact integers. The counts are recomputed whenever a strike is confirmed, and are re-evaluated against the logical clock before every request; whenever a count has drifted — for example a strike aging out of the window — the fresh counts and level are persisted.

When conditions warrant, a senior biologist drafts an `OperationalAdvisory` declaring a `hazard_level` of `LOW`, `ELEVATED`, `HIGH`, or `CRITICAL` for a forward window, supplying the `airport_id`, the `issued_by_biologist_id`, the `issued_at` timestamp, the `effective_from` and `effective_to` bounds (with `effective_to` strictly after `effective_from`), a `reason_code` of `STRIKE_SPIKE`, `MIGRATION`, `NESTING`, `HABITAT_CHANGE`, `WEATHER`, or `OTHER`, and optionally a `supersedes_advisory_id` referencing the advisory it replaces. New advisories enter in `DRAFT`. Activation moves `DRAFT → ACTIVE` and requires seniority, a well-formed effective window, and — when `supersedes_advisory_id` is set — that the referenced advisory is currently `ACTIVE` and on the same airport (a violation surfaces `ERR_INVALID_STATE` (HTTP 409)); on success the referenced advisory is cascaded from `ACTIVE` to `SUPERSEDED` and the airport's hazard level is recomputed. Because activation mutates the parent airport's posture, the activation call requires `expected_airport_version` in the request body; a mismatch with the airport's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). An active advisory is moved to `EXPIRED` by the system when the logical clock passes `effective_to`, again recomputing the airport's hazard level. The issuing biologist may cancel a draft advisory (`DRAFT → CANCELLED`); cancellation is restricted to the original issuer, and attempts by anyone else are rejected with `ERR_UNAUTHORIZED` (HTTP 403). The advisory list view supports filtering by `airport_id`, `status`, `hazard_level`, `reason_code`, `issued_by_biologist_id`, and `supersedes_advisory_id`.

Runway closures are the operational arm of the program. A biologist requests a closure by supplying the `airport_id`, the `runway_designator`, the `requested_by_biologist_id`, the requested `closure_start` and `closure_end` UTC timestamps, and a `reason` of `CARCASS_RECOVERY`, `HAZARD_SWEEP`, `STRIKE_RESPONSE`, `MITIGATION_WORK`, or `OTHER`. The window must be well-formed — `closure_end` strictly after `closure_start` — and the total duration must not exceed four hours; a malformed window surfaces `ERR_INVALID_WINDOW` (HTTP 422) and an over-long closure surfaces `ERR_CLOSURE_DURATION_EXCEEDED` (HTTP 422). Overlap with existing closures is checked at request time and again at authorize time: two closures at the same airport on the same runway conflict when one's start precedes the other's end and vice versa, with the further rule that every `AUTHORIZED` or `ACTIVE` closure's end is padded by a fifteen-minute safety buffer for conflict-check purposes only, and adjacent endpoints without overlap do not conflict. A conflicting request is rejected with `ERR_CLOSURE_CONFLICT` (HTTP 409). New closures enter in `REQUESTED`. The closure list view supports filtering by `airport_id`, `runway_designator`, `status`, `requested_by_biologist_id`, and `authorized_by_controller_id`.

Authorization moves `REQUESTED → AUTHORIZED` and is performed by an `ATCController` whose `airport_id` matches the closure's `airport_id`; a cross-facility attempt is rejected with `ERR_CROSS_FACILITY_FORBIDDEN` (HTTP 403). Authorization stamps `authorized_by_controller_id`. The system moves an authorized closure `AUTHORIZED → ACTIVE` when the logical clock reaches `closure_start`. Release moves `ACTIVE → RELEASED`, must be performed by a controller at the same airport, and is blocked while the airport is at `CRITICAL` hazard; release stamps `actual_released_at` with the current time. A controller may also deny a `REQUESTED` closure (`REQUESTED → DENIED`), again restricted to the same airport. The requesting biologist may cancel a `REQUESTED` closure (`REQUESTED → CANCELLED`); attempts by anyone else are rejected with `ERR_UNAUTHORIZED` (HTTP 403).

### 3.6. Annual Plan, Training Currency, and Trending

Each calendar year, the biologist team produces an `AnnualPlan`. Creating one supplies the `airport_id`, the `plan_year` between 2000 and 2100, and an optional free-form `version_note`. New plans enter in `DRAFT`. At most one plan per airport per year may be in `SUBMITTED_FOR_REVIEW`, `APPROVED`, or `PUBLISHED` at any time; a duplicate attempt surfaces `ERR_PLAN_DUPLICATE_YEAR` (HTTP 409), enforced both at creation and at submission. Submission moves `DRAFT → SUBMITTED_FOR_REVIEW` and stamps `submitted_at`; as a courtesy, submission also surfaces a non-blocking warning — a `warnings` array in the response `meta` with one `{training_record_id, biologist_id, expires_at}` entry per record — listing any training records held by biologists at the airport whose `expires_at` falls before December 31 of the plan year. A `RegulatorAgent` may return the plan (`SUBMITTED_FOR_REVIEW → RETURNED`) or approve it (`SUBMITTED_FOR_REVIEW → APPROVED`); approval stamps `approved_by_regulator_id`. A returned plan can be revised by a biologist back to `DRAFT` (`RETURNED → DRAFT`). Publication moves `APPROVED → PUBLISHED`, is blocked while the airport is at `CRITICAL`, stamps `published_at`, and — because it supersedes any prior published plan for the same airport — both cascades that prior plan to `SUPERSEDED` and bumps the airport's `version`. Because publication mutates the airport, the publish call also requires `expected_airport_version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). The plan list view supports filtering by `airport_id`, `plan_year`, `status`, and `approved_by_regulator_id`.

Training currency is tracked per biologist. Recording a completed training supplies the `biologist_id`, the `course_code`, the `completed_at` ISO date, and an `expires_at` ISO date that must be strictly after `completed_at`; a record with the dates out of order surfaces `ERR_INVALID_WINDOW`. New records enter in `VALID`. The system moves a `VALID` record to `EXPIRING_SOON` when the logical clock reaches thirty days before `expires_at`, and moves either a `VALID` or `EXPIRING_SOON` record to `EXPIRED` once past `expires_at`. A `RegulatorAgent` may revoke a `VALID` record (`VALID → REVOKED`). The training-record list view supports filtering by `biologist_id`, `status`, and `course_code`.

Two derived views support the planning conversation. A per-airport species-by-season trend report counts, for each species and each meteorological season over a lookback window, the number of `CONFIRMED` strikes at the airport where `strike_at` falls in the window and in the season, plus the number of `CLOSED` dispersal activities for that species in the same season and the total `animals_taken_lethal` across those dispersals. Meteorological seasons follow the Northern Hemisphere convention — December, January, and February are `WINTER`; March through May are `SPRING`; June through August are `SUMMER`; September through November are `AUTUMN`. The lookback defaults to three hundred sixty-five days when `lookback_days` is not supplied; a supplied `lookback_days` must be an integer of at least one, and anything else is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The strike window is inclusive at both ends, counting `CONFIRMED` strikes with `strike_at` between now minus the lookback and now. Each report row carries the species' `species_id` and `common_name`, the meteorological `season`, the `strike_count`, the `dispersal_count` of `CLOSED` dispersals, and the `lethal_take_total` summed across those dispersals, and the response returns the rows under a `rows` key in the `data` object. A species-season appears as a row whenever it has at least one qualifying strike or dispersal, so a row may legitimately carry a zero `strike_count` or a zero `dispersal_count`. Rows are sorted by strike count descending, ties broken by the species' `common_name` ascending, and any remaining ties — the same species appearing in more than one season — are ordered by season in the meteorological sequence `WINTER`, `SPRING`, `SUMMER`, `AUTUMN`.

A per-airport training-compliance view rolls up currency across the airport's active biologists. Each biologist's score is the average of their training-record contributions — `VALID` records contribute one, `EXPIRING_SOON` records contribute one-half, and `EXPIRED` or `REVOKED` records contribute zero — averaged across that biologist's records, with a biologist who has no records counting as a zero contribution over a denominator of one. The airport-level `airport_compliance_pct` is the mean of the per-biologist scores multiplied by one hundred, rounded half-up to two decimal places, with the same divide-by-one protection when an airport has no active biologists. The response `data` carries `airport_compliance_pct` alongside a `per_biologist` array — in biologist creation order — whose entries carry `biologist_id`, `full_name`, `training_record_count`, and the biologist's `score`.

## 4. Endpoint Definitions

All endpoints are served under `/wildlife`. Endpoints that create a new resource return HTTP 201 on success with the created resource in the response; endpoints that modify an existing resource (state transitions, updates) return HTTP 200 with the updated resource. All list endpoints return HTTP 200 with the paginated envelope described in §2.2 and §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/wildlife/airports` | Create a new airport record | AirportAdmin |
| GET | `/wildlife/airports` | List airports | AirportAdmin, WildlifeBiologist, ATCController, RegulatorAgent |
| GET | `/wildlife/airports/{id}` | Fetch one airport with derived hazard fields | AirportAdmin, WildlifeBiologist, ATCController, RegulatorAgent |
| GET | `/wildlife/airports/{id}/hazard-preview` | What-if projection of hazard level at as_of timestamp | WildlifeBiologist, AirportAdmin |
| GET | `/wildlife/airports/{id}/trends/species-seasonal` | Species x season trending over lookback window | WildlifeBiologist, AirportAdmin, RegulatorAgent |
| GET | `/wildlife/airports/{id}/training-compliance` | Weighted training currency score across biologists at airport | WildlifeBiologist, AirportAdmin, RegulatorAgent |
| POST | `/wildlife/species` | Register a species | AirportAdmin |
| GET | `/wildlife/species` | List species | AirportAdmin, WildlifeBiologist, ATCController, RegulatorAgent |
| GET | `/wildlife/species/{id}` | Fetch a species | AirportAdmin, WildlifeBiologist, ATCController, RegulatorAgent |
| POST | `/wildlife/biologists` | Register a biologist | AirportAdmin |
| GET | `/wildlife/biologists` | List biologists | AirportAdmin, WildlifeBiologist, RegulatorAgent |
| GET | `/wildlife/biologists/{id}` | Fetch biologist | AirportAdmin, WildlifeBiologist, RegulatorAgent |
| POST | `/wildlife/atc-controllers` | Register an ATC controller | AirportAdmin |
| GET | `/wildlife/atc-controllers` | List ATC controllers | AirportAdmin, ATCController |
| GET | `/wildlife/atc-controllers/{id}` | Fetch ATC controller | AirportAdmin, ATCController |
| POST | `/wildlife/regulators` | Register a regulator agent | AirportAdmin |
| GET | `/wildlife/regulators/{id}` | Fetch regulator | AirportAdmin, RegulatorAgent |
| POST | `/wildlife/strike-reports` | Log a new strike report in DRAFT | WildlifeBiologist |
| GET | `/wildlife/strike-reports` | List strike reports | AirportAdmin, WildlifeBiologist, RegulatorAgent |
| GET | `/wildlife/strike-reports/{id}` | Fetch one strike report | AirportAdmin, WildlifeBiologist, RegulatorAgent |
| POST | `/wildlife/strike-reports/{id}/submit` | DRAFT to SUBMITTED | WildlifeBiologist |
| POST | `/wildlife/strike-reports/{id}/begin-review` | SUBMITTED to UNDER_REVIEW | WildlifeBiologist |
| POST | `/wildlife/strike-reports/{id}/confirm` | UNDER_REVIEW to CONFIRMED; recomputes hazard; may auto-create carcass | WildlifeBiologist |
| POST | `/wildlife/strike-reports/{id}/reject` | UNDER_REVIEW to REJECTED | WildlifeBiologist |
| POST | `/wildlife/strike-reports/{id}/return-to-draft` | SUBMITTED to DRAFT (reporter self-service) | WildlifeBiologist |
| POST | `/wildlife/strike-reports/{id}/carcass-records` | Manually create a carcass record under a strike report | WildlifeBiologist |
| GET | `/wildlife/strike-reports/{id}/carcass-records` | List carcass records under a strike report | WildlifeBiologist, AirportAdmin, RegulatorAgent |
| GET | `/wildlife/carcass-records` | List carcass records | WildlifeBiologist, AirportAdmin, RegulatorAgent |
| GET | `/wildlife/carcass-records/{id}` | Fetch one carcass record | WildlifeBiologist, AirportAdmin, RegulatorAgent |
| POST | `/wildlife/carcass-records/{id}/send-to-lab` | COLLECTED to PENDING_ID | WildlifeBiologist |
| POST | `/wildlife/carcass-records/{id}/identify` | COLLECTED or PENDING_ID to IDENTIFIED; may cascade strike to AMENDED | WildlifeBiologist |
| POST | `/wildlife/carcass-records/{id}/dispute` | IDENTIFIED to DISPUTED (senior, non-identifier) | WildlifeBiologist |
| POST | `/wildlife/carcass-records/{id}/resolve` | DISPUTED to RESOLVED | WildlifeBiologist |
| POST | `/wildlife/habitat-assessments` | Create habitat assessment (computes composite score) | WildlifeBiologist |
| GET | `/wildlife/habitat-assessments` | List habitat assessments | WildlifeBiologist, AirportAdmin, RegulatorAgent |
| GET | `/wildlife/habitat-assessments/{id}` | Fetch one habitat assessment | WildlifeBiologist, AirportAdmin, RegulatorAgent |
| POST | `/wildlife/habitat-assessments/{id}/mitigation-actions` | Propose mitigation under an assessment | WildlifeBiologist |
| GET | `/wildlife/habitat-assessments/{id}/mitigation-actions` | List mitigations under an assessment | WildlifeBiologist, AirportAdmin, RegulatorAgent |
| GET | `/wildlife/mitigation-actions` | List mitigation actions | WildlifeBiologist, AirportAdmin, RegulatorAgent |
| GET | `/wildlife/mitigation-actions/{id}` | Fetch one mitigation action | WildlifeBiologist, AirportAdmin, RegulatorAgent |
| POST | `/wildlife/mitigation-actions/{id}/approve` | PROPOSED to APPROVED | WildlifeBiologist |
| POST | `/wildlife/mitigation-actions/{id}/reject` | PROPOSED to REJECTED | WildlifeBiologist |
| POST | `/wildlife/mitigation-actions/{id}/start-work` | APPROVED to IN_PROGRESS | WildlifeBiologist |
| POST | `/wildlife/mitigation-actions/{id}/verify` | IN_PROGRESS to VERIFIED | WildlifeBiologist |
| POST | `/wildlife/mitigation-actions/{id}/complete` | VERIFIED to COMPLETED; recomputes airport hazard | WildlifeBiologist |
| POST | `/wildlife/mitigation-actions/{id}/cancel` | PROPOSED to CANCELLED | WildlifeBiologist |
| POST | `/wildlife/dispersal-activities` | Log a dispersal | WildlifeBiologist |
| GET | `/wildlife/dispersal-activities` | List dispersals | WildlifeBiologist, AirportAdmin, RegulatorAgent |
| GET | `/wildlife/dispersal-activities/{id}` | Fetch one dispersal | WildlifeBiologist, AirportAdmin, RegulatorAgent |
| POST | `/wildlife/dispersal-activities/{id}/review` | LOGGED to REVIEWED (segregation of duties) | WildlifeBiologist |
| POST | `/wildlife/dispersal-activities/{id}/close` | REVIEWED or FLAGGED to CLOSED; reconciles permit take | WildlifeBiologist |
| POST | `/wildlife/take-permits` | Issue a new take permit | RegulatorAgent |
| GET | `/wildlife/take-permits` | List take permits | WildlifeBiologist, AirportAdmin, RegulatorAgent |
| GET | `/wildlife/take-permits/{id}` | Fetch one permit | WildlifeBiologist, AirportAdmin, RegulatorAgent |
| GET | `/wildlife/take-permits/{id}/take-preview` | Projected take_consumed including REVIEWED (provisional) | WildlifeBiologist, AirportAdmin, RegulatorAgent |
| POST | `/wildlife/take-permits/{id}/submit-annual-report` | ACTIVE or EXHAUSTED to CLOSED with annual report | RegulatorAgent |
| POST | `/wildlife/take-permits/{id}/revoke` | ACTIVE to REVOKED; flags LOGGED dispersals referencing permit | RegulatorAgent |
| POST | `/wildlife/operational-advisories` | Create an advisory in DRAFT | WildlifeBiologist |
| GET | `/wildlife/operational-advisories` | List advisories | WildlifeBiologist, AirportAdmin, RegulatorAgent, ATCController |
| GET | `/wildlife/operational-advisories/{id}` | Fetch one advisory | WildlifeBiologist, AirportAdmin, RegulatorAgent, ATCController |
| POST | `/wildlife/operational-advisories/{id}/activate` | DRAFT to ACTIVE; supersedes prior advisory if referenced | WildlifeBiologist |
| POST | `/wildlife/operational-advisories/{id}/cancel` | DRAFT to CANCELLED | WildlifeBiologist |
| POST | `/wildlife/runway-closures` | Request a runway closure | WildlifeBiologist |
| GET | `/wildlife/runway-closures` | List runway closures | WildlifeBiologist, AirportAdmin, ATCController, RegulatorAgent |
| GET | `/wildlife/runway-closures/{id}` | Fetch one closure | WildlifeBiologist, AirportAdmin, ATCController, RegulatorAgent |
| POST | `/wildlife/runway-closures/{id}/authorize` | REQUESTED to AUTHORIZED (ATC at same airport) | ATCController |
| POST | `/wildlife/runway-closures/{id}/deny` | REQUESTED to DENIED | ATCController |
| POST | `/wildlife/runway-closures/{id}/release` | ACTIVE to RELEASED | ATCController |
| POST | `/wildlife/runway-closures/{id}/cancel` | REQUESTED to CANCELLED (requester only) | WildlifeBiologist |
| POST | `/wildlife/annual-plans` | Create annual plan in DRAFT | WildlifeBiologist |
| GET | `/wildlife/annual-plans` | List annual plans | WildlifeBiologist, AirportAdmin, RegulatorAgent |
| GET | `/wildlife/annual-plans/{id}` | Fetch one plan | WildlifeBiologist, AirportAdmin, RegulatorAgent |
| POST | `/wildlife/annual-plans/{id}/submit` | DRAFT to SUBMITTED_FOR_REVIEW | WildlifeBiologist |
| POST | `/wildlife/annual-plans/{id}/return-for-revision` | SUBMITTED_FOR_REVIEW to RETURNED | RegulatorAgent |
| POST | `/wildlife/annual-plans/{id}/revise` | RETURNED to DRAFT | WildlifeBiologist |
| POST | `/wildlife/annual-plans/{id}/approve` | SUBMITTED_FOR_REVIEW to APPROVED | RegulatorAgent |
| POST | `/wildlife/annual-plans/{id}/publish` | APPROVED to PUBLISHED; supersedes prior published plan | WildlifeBiologist |
| POST | `/wildlife/training-records` | Record a completed training | WildlifeBiologist |
| GET | `/wildlife/training-records` | List training records | WildlifeBiologist, AirportAdmin, RegulatorAgent |
| GET | `/wildlife/training-records/{id}` | Fetch one training record | WildlifeBiologist, AirportAdmin, RegulatorAgent |
| POST | `/wildlife/training-records/{id}/revoke` | VALID to REVOKED | RegulatorAgent |
| POST | `/wildlife/_clock/set_current_utc` | Set the logical clock to an ISO8601 UTC timestamp | AirportAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_FK_NOT_FOUND | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_HAZARD_CRITICAL_BLOCK | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_SENIOR_REQUIRED | 403 |
| ERR_INVALID_WINDOW | 422 |
| ERR_CLOSURE_CONFLICT | 409 |
| ERR_CLOSURE_DURATION_EXCEEDED | 422 |
| ERR_TAKE_PERMIT_REQUIRED | 422 |
| ERR_FEDERAL_PERMIT_REQUIRED | 422 |
| ERR_PERMIT_OUTSIDE_WINDOW | 422 |
| ERR_TAKE_BUDGET_EXCEEDED | 422 |
| ERR_PLAN_DUPLICATE_YEAR | 409 |
| ERR_ID_METHOD_PENDING | 422 |
| ERR_MITIGATION_REQUIRED | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_ENUM | 400 |
| ERR_CROSS_FACILITY_FORBIDDEN | 403 |
