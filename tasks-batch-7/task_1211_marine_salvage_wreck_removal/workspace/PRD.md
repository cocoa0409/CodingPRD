# Marine Salvage & Wreck Removal API — Product Requirements Document

## 1. Introduction

Marine salvage is a business of irreversible decisions made under weather, regulatory, and commercial pressure. When a vessel grounds, collides, burns, or sinks, the answering contractor must size the incident, commit equipment before the weather window closes, negotiate commercial terms with an owner who may be adversarial, satisfy the coast guard, port, and environmental agencies, and ultimately prove every hour and every dollar to an insurer. This document specifies the Marine Salvage & Wreck Removal API, the system of record a salvage contractor uses to run that entire arc: casualty intake and independent survey, salvage planning, contract negotiation under both fixed-price and no-cure-no-pay forms, security lodgement, permit coordination, equipment chartering under wave-height limits, pollution response with special-compensation accounting, recovery and disposition of salved property under lien, and the final salvage award — whether agreed between the parties or published by an arbitrator.

The API is built around a segregation-of-duties operating model: the surveyor who assesses a casualty never approves that assessment, the master who drafts the plan never approves it, and the officer who negotiates the contract never runs the operation. State is managed as interlocking lifecycle machines whose transitions cascade — a single pollution escalation can suspend every running phase and standby every chartered asset, while completing the last phase of a contract bubbles all the way up to the casualty file. Money and mass are conserved quantities throughout: lodged security is always fully accounted for across its buckets, and every tonne of recovered property is tracked from the moment it is salved until it is redelivered, sold, or scrapped.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response shape, time, money, validation order, and concurrency. Everything here applies uniformly to every endpoint in §4.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operator's capacity. A request missing either header, or presenting a role name outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER`. A request whose declared role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes seven roles, spelled exactly as follows: `SalvageMaster`, the on-scene salvage commander who reports casualties, drafts plans, and runs mobilization, charters, weather, phases, property logging, and insurer documentation; `ContractsOfficer`, the commercial desk responsible for negotiation, signature, security funds, liens, awards, and settlement; `MarineSurveyor`, the independent surveyor who authors incident assessments and property value surveys; `EnvironmentalOfficer`, the environmental liaison who runs agency permits and the pollution response lifecycle; `OperationsDirector`, the contractor's operations director who approves assessments and plans, owns the asset and storage-site registries, verifies surveyed values, and closes casualties; `Arbitrator`, the salvage arbitrator who publishes and re-decides awards; and `InsurerSurveyor`, the insurer's surveyor who reviews documentation packs.

For every role, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow captures an actor — for example as `assessor_id` on an Assessment, `drafter_id` on a SalvagePlan, `approver_id` on an approved plan, `reviewer_id` on a reviewed assessment, or `surveyor_id` on a surveyed property lot — but it never compares `X-User-ID` to any entity's `id`. Segregation-of-duties checks compare `X-User-ID` against these recorded actor fields, not against resource identifiers.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Every list response sorts its resources by creation timestamp (`created_at`) in ascending order, and every list response includes the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and Scheduled Sweeps

A single logical clock governs every time-dependent rule in the system — charter windows, permit validity, weather feasibility, and all recorded timestamps such as `on_hire_at`, `off_hire_at`, and `activated_at`. Before any client has set it, the logical clock reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time. Any declared role may advance the clock through the clock-setting capability (`POST /_clock/set_current_utc`), supplying the target instant in the `to_iso8601` field.

Advancing the clock triggers an automatic expiry sweep at the new time: every Permit whose status is `GRANTED`, `SUSPENDED`, or `REQUESTED` and whose `valid_to` is strictly earlier than the new time transitions to `EXPIRED`, and every WeatherWindow in `OPEN` whose `window_end` is strictly earlier than the new time transitions to `EXPIRED`. The capability's response reports the new `current_utc` together with the identifiers swept, `expired_permit_ids` and `expired_window_ids`, so clients can observe exactly which records the sweep touched.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records creation as an ISO 8601 UTC value with three fractional digits. The `updated_at` timestamp refreshes on every mutation of the resource, including system-driven mutations caused by cascades. The `version` is an integer that starts at its initial value on creation and increments by 1 on every mutation; clients use it for optimistic concurrency control where §2.9 applies. Documentation entries are the sole exception to this convention: a DocEntry carries only `id` and `created_at`, and both `updated_at` and `version` are absent from it, because entries are immutable once appended. System-managed fields that capture a specific later event — such as `reviewer_id`, `approver_id`, `surveyor_id`, `on_hire_at`, `off_hire_at`, `activated_at`, `weather_window_id`, `storage_site_id`, `verified_value_cents`, `terminate_reason`, `agreed_amount_cents`, `awarded_amount_cents`, `paid_amount_cents`, `final_exposure_cents`, `total_cost_cents`, `review_notes`, and a charter's `linked_phase_id` — remain null until the workflow event that populates them occurs, and counters and accumulators such as `appeal_count`, `standby_hours`, `provisional_exposure_cents`, `required_count`, `satisfied_count`, and the deposit and mass buckets start at zero unless §3 states otherwise.

### 2.6. Money, Mass, and Conservation Invariants

All monetary amounts are integer cents, and all computed monetary values are rounded half up to zero decimal places — integer cents — at the point the calculation's rounding rule specifies. Certain calculations pin a rounding order rather than rounding once at the end: each rate line is rounded to integer cents first, then multiplied by its day count, and only then are the lines summed. Summing unrounded line values and rounding a single time at the end produces a different result and is non-conformant.

Two conservation invariants hold at all times and are re-verified on every mutation of the respective resource. For security funds, a deposit's `lodged_amount_cents` always equals the sum of its `held_cents`, `released_cents`, and `applied_cents`; the lodged figure is fixed at creation and never changes thereafter, so forward disbursements and any compensating actions only move money between the three buckets. For recovered property, a lot's `quantity_tonnes` always equals the sum of its `redelivered_tonnes`, `sold_tonnes`, `disposed_tonnes`, and `in_custody_tonnes`; dispositions move mass out of custody into exactly one bucket and never alter the total.

### 2.7. Validation Pipeline and Error Priority

Every request passes through a fixed pipeline of validation tiers, evaluated in ascending priority order, so that an earlier failure masks later checks on the same request. The order is normative.

First, at priority 0, request schema validation: all required fields present, enum values valid, numeric amounts and quantities positive where required, datetime ranges valid (`valid_to` later than `valid_from`, `window_end` later than `window_start`), and conditional fields honored — `fixed_price_cents` is required and must be positive exactly when `form` is `FIXED_PRICE` and is forbidden otherwise, and `pollution_event_id` is required exactly when `purpose` is `POLLUTION_RESPONSE` and must be null otherwise. Any failure here yields `ERR_INVALID_REQUEST`. Second, at priority 1, the context headers are validated (`ERR_MISSING_OR_INVALID_CONTEXT_HEADER`), and at priority 2 the declared role is checked against the endpoint's authorized roles (`ERR_FORBIDDEN_ROLE`). Third, at priority 3, existence of every referenced identifier is confirmed (`ERR_NOT_FOUND`). Fourth, at priority 4, segregation of duties is enforced on the four review-style actions — assessment approval, assessment rejection, plan approval, and property value verification — where the acting operator must not be the recorded author of the record (`ERR_SOD_VIOLATION`).

Priority 5 covers state permission: an action whose target is in the wrong from-state is rejected with `ERR_INVALID_STATE_TRANSITION`, while an action attempted on a resource already in a terminal state is rejected with `ERR_ALREADY_TERMINAL`; both share one tier, and when both conditions apply at once the terminal-state rejection takes precedence. Priority 6 holds the environmental and weather safety gates (`ERR_ENV_HOLD_ACTIVE`, `ERR_ENV_CLEARANCE_REQUIRED`, `ERR_WEATHER_LIMIT_EXCEEDED`, `ERR_WEATHER_WINDOW_INFEASIBLE`). Priority 7 holds the temporal and window rules (`ERR_PERMIT_MISSING`, `ERR_PERMIT_NOT_VALID`, `ERR_CHARTER_OVERLAP`, `ERR_STORAGE_CAPACITY_EXCEEDED`, `ERR_CHARTER_WINDOW_NOT_OPEN`). Priority 8 holds the referenced-entity state gates (`ERR_ASSESSMENT_NOT_APPROVED`, `ERR_PLAN_NOT_APPROVED`, `ERR_CONTRACT_NOT_ACTIVE`, `ERR_PROPERTIES_NOT_VERIFIED`, `ERR_PROPERTIES_NOT_DISPOSED`, `ERR_LIEN_ACTIVE`, `ERR_ASSET_CLASS_NOT_REQUIRED`, `ERR_DOCS_NOT_ACCEPTED`). Priority 9 holds the aggregate, uniqueness, and argument constraints (`ERR_DUPLICATE_ACTIVE_CONTRACT`, `ERR_DUPLICATE_OPEN_DOC_PACK`, `ERR_AWARD_ALREADY_EXISTS`, `ERR_QUANTITY_EXCEEDS_REMAINING`, `ERR_POLLUTION_TIER_NOT_RAISED`, `ERR_DOC_ENTRY_INVALID`, `ERR_TERMINATION_NOT_ALLOWED`, `ERR_NO_CURE_REQUIRES_NCNP`, `ERR_CASUALTY_NOT_CLOSABLE`).

Money gates are evaluated after everything else, at priority 10 (`ERR_SECURITY_INSUFFICIENT`, `ERR_SECURITY_DISBURSE_EXCEEDS_HELD`, `ERR_SECURITY_DISBURSE_NOT_ALLOWED`, `ERR_DOC_INCOMPLETE`). This ordering is observable at contract activation: a contract that fails both its environmental clearance and its security coverage surfaces the safety rejection `ERR_ENV_CLEARANCE_REQUIRED`, never the fiscal one, because safety is reported before fiscal. Last, at priority 11, the optimistic-concurrency fields are compared (`ERR_STALE_CONTRACT_VERSION`, `ERR_STALE_CASUALTY_VERSION`).

### 2.8. Nested and Referenced Resource Validation

Requests that target a resource through a path of identifiers are validated strictly left to right: the server confirms the first identifier exists before examining the second, and a request is rejected with `ERR_NOT_FOUND` at the first identifier — `casualty_id`, `assessment_id`, `plan_id`, `contract_id`, `security_id`, `permit_id`, `asset_id`, `charter_id`, `window_id`, `phase_id`, `event_id`, `property_id`, `site_id`, `award_id`, or `pack_id` — that does not correspond to an existing resource. Identifiers referenced inside a request body are validated the same way: a payload naming a `casualty_id`, `plan_id`, `contract_id`, `equipment_asset_id`, `weather_window_id`, a list of `charter_ids`, a `storage_site_id`, or a documentation `ref_id` is rejected with `ERR_NOT_FOUND` when any referenced record does not exist.

### 2.9. Optimistic Concurrency Control

Two write operations carry optimistic concurrency control, and in both the version field is a non-optional input. Filing a counter-offer against a salvage contract requires `expected_contract_version` to equal the contract's current `version` at the moment of the write; if another writer has advanced the contract's version since the client last read it — for example because the other party's counter has just been recorded, legitimately superseding the terms under negotiation — the request is rejected with `ERR_STALE_CONTRACT_VERSION` and HTTP status 412, preventing the client from overwriting a negotiation state it has not observed. Submitting an incident assessment requires `expected_casualty_version` to equal the casualty's current `version`; a mismatch is rejected with `ERR_STALE_CASUALTY_VERSION` and HTTP status 412, because creating an assessment legitimately supersedes any sibling still under review, so a stale writer must re-read before adding another survey. No other endpoint accepts a version field; the stale-state behavior of every other write is governed by state preconditions rather than version comparison.

### 2.10. Cascading State Propagation and Hierarchical Consistency

The server keeps parent and child lifecycles aligned without requiring clients to drive each level. Three named cascades recur throughout §3. Cascade A runs from pollution to operations: a pollution event change recomputes the casualty's environmental posture (link 1); the posture entering `ENV_HOLD` forces every `ACTIVE` operation phase of the casualty's contracts into `ENV_SUSPENDED` (link 2); and each suspended phase pushes its linked on-hire charters into `STANDBY_ENV` (link 3). Cascade B runs from operations upward: when a phase completion leaves every phase of a contract in a terminal state, the contract moves from `ACTIVE` to `PERFORMANCE_COMPLETE` (link 1), and that in turn moves the casualty from `IN_OPERATION` to `OPERATIONS_COMPLETE` (link 2), which is the gate that makes recovered property disposition-eligible. The termination cascade runs when an active contract ends in no-cure termination: open phases are aborted, hired and standby charters are taken off hire or cancelled, and property becomes disposition-eligible. Every system-driven mutation — whether an automatic lifecycle bump, a posture recompute, or a cascade hop — refreshes the affected resource's `updated_at` and increments its `version` independently, exactly as a client-driven mutation would.

## 3. Business Logic & Workflows

### 3.1. Casualty Intake and the Independent Assessment

Everything begins when a `SalvageMaster` reports a casualty: the vessel's `vessel_name`, the `casualty_type` — one of `GROUNDING`, `COLLISION`, `FIRE`, or `SUNK` — the owner-declared `declared_salved_value_cents` representing the value of vessel and cargo at risk (a positive integer), a free-text `position`, and an optional `pollutant_inventory_note` describing bunkers or cargo pollutants aboard, which defaults to an empty string. A new casualty opens with `lifecycle_status` set to `REPORTED` and `env_posture` set to `ENV_CLEAR`. The casualty list can be filtered by `lifecycle_status` and `env_posture`.

A `MarineSurveyor` then files an incident assessment against the casualty, carrying the target `casualty_id`, the surveyor's reading of the worst credible pollution outcome in `pollution_risk_tier` (`TIER_1`, `TIER_2`, or `TIER_3`), a boolean `wreck_removal_required` marking whether full removal rather than mere refloat is needed, a positive `estimated_cost_cents`, optional free-text `notes` defaulting to empty, and — because assessment creation participates in optimistic concurrency control — the `expected_casualty_version` described in §2.9. The new assessment opens in `SUBMITTED`, records the creator's header identity as `assessor_id`, and receives a `casualty_seq`: a monotone sequence number assigned within the casualty at creation, which provides deterministic recency ordering and is never derived from resource identifiers. Creating an assessment automatically transitions every sibling assessment of the same casualty still in `SUBMITTED` to `SUPERSEDED` (bumping each such sibling's `version`), and the creation itself increments the casualty's `version` by 1 — which is precisely the drift the next surveyor's `expected_casualty_version` must reflect. The assessment list can be filtered by `casualty_id` and `status`.

Review sits with the `OperationsDirector`, and segregation of duties forbids the reviewer from being the author: if `X-User-ID` equals the assessment's `assessor_id`, both approval and rejection are rejected with `ERR_SOD_VIOLATION`. Approval moves the assessment from `SUBMITTED` to `APPROVED`, stamps `reviewer_id` with the acting operator, and automatically lifts the casualty's `lifecycle_status` from `REPORTED` to `ASSESSED` (refreshing the casualty's `updated_at` and incrementing its `version`). Rejection moves the assessment from `SUBMITTED` to `REJECTED` and likewise stamps `reviewer_id`, without touching the casualty. Once an assessment reaches `APPROVED`, `REJECTED`, or `SUPERSEDED` it is terminal, and any further action on it meets `ERR_ALREADY_TERMINAL`.

### 3.2. Salvage Planning and Approval

With an approved assessment in hand, a `SalvageMaster` drafts a salvage plan against the casualty, supplying the `casualty_id`, a salvage `method` of `REFLOAT`, `LIGHTERING`, `TOWAGE`, or `WRECK_REMOVAL`, and a non-empty `required_equipment_classes` array drawn from the equipment classes `TUG`, `CRANE_BARGE`, `PONTOON`, and `OIL_RESPONSE`. The draft records its author as `drafter_id` and opens in `DRAFT`. Plans are listed with filters on `casualty_id` and `status`.

Submission by a `SalvageMaster` advances the plan from `DRAFT` to `SUBMITTED`. Approval by an `OperationsDirector` enforces two preconditions, in the pipeline order of §2.7: first the segregation-of-duties rule that the approver's identity must differ from the plan's `drafter_id` (`ERR_SOD_VIOLATION`), and then the referential gate that an assessment of the same casualty in status `APPROVED` must exist (`ERR_ASSESSMENT_NOT_APPROVED`). Approval stamps `approver_id` with the acting director, moves the plan to `APPROVED`, and automatically lifts the casualty from `ASSESSED` to `PLANNED`. Rejection by an `OperationsDirector` does not kill the plan: it returns the plan from `SUBMITTED` to `DRAFT` and increments the plan's `version`, and this draft–submit–reject revision loop may repeat without bound.

### 3.3. Contract Negotiation, Signature, and Termination

Commercial terms are handled by the `ContractsOfficer`, who creates a salvage contract with the `casualty_id`, the chosen `plan_id`, the contract `form` — `FIXED_PRICE` or `NO_CURE_NO_PAY` — an optional `fixed_price_cents`, and an optional `scopic_clause_included` flag that defaults to false and governs whether SCOPIC-style special-compensation netting applies later. The schema rule on `fixed_price_cents` is strict: it must be present and positive exactly when the form is `FIXED_PRICE`, and it is forbidden on a `NO_CURE_NO_PAY` contract. A casualty supports at most one contract whose status is not `SETTLED` or `TERMINATED`; attempting to create a second non-terminal contract on the same casualty fails with `ERR_DUPLICATE_ACTIVE_CONTRACT`. A new contract opens in `DRAFT` with `negotiation_round` set to 0. Contracts are listed with filters on `casualty_id`, `plan_id`, and `status`.

Negotiation is an explicit cycle. Issuing the opening offer moves the contract from `DRAFT` to `OFFERED`, sets `negotiation_round` to 1, and increments the contract's `version`. Each counter-offer flips the contract between `OFFERED` and `COUNTERED`, increments `negotiation_round` by 1, and increments `version`; the counter payload carries the mandatory `expected_contract_version` of §2.9 — a stale read rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412) — plus an optional free-text `terms_note`. The offer–counter cycle between `OFFERED` and `COUNTERED` may iterate without bound, with the round counter climbing on every hop.

Signature by a `ContractsOfficer` moves the contract from either `OFFERED` or `COUNTERED` to `SIGNED`. Signing is gated on the paperwork beneath the deal: the latest-created assessment of the casualty must exist in `APPROVED` status, otherwise the sign is rejected with `ERR_ASSESSMENT_NOT_APPROVED`, and the contract's `plan_id` must reference a plan in `APPROVED` status, otherwise it is rejected with `ERR_PLAN_NOT_APPROVED`. At the moment of signature the server computes two figures and stores them on the contract. The provisional award: for a `NO_CURE_NO_PAY` contract, `provisional_award_cents` is twelve percent of the casualty's `declared_salved_value_cents`, rounded half up to integer cents; for a `FIXED_PRICE` contract it is simply the `fixed_price_cents`. The security requirement: for a `NO_CURE_NO_PAY` contract, `security_required_cents` is the provisional award multiplied by 1.25, rounded half up to integer cents; for a `FIXED_PRICE` contract it is thirty percent of the `fixed_price_cents`, rounded half up to integer cents. The provisional figure deliberately ignores tiers, risk, pollution, and verification — it exists to size the security demand. Signing also lifts the casualty from `PLANNED` to `CONTRACTED` and increments the contract's `version`.

Termination is available in two flavors, and the reason is supplied in the `reason` field. Mutual termination, with `reason` set to `MUTUAL`, is allowed from `DRAFT`, `OFFERED`, `COUNTERED`, or `SIGNED`; it sets `terminate_reason` to `MUTUAL` and makes the contract's security deposits release-eligible. From `ACTIVE`, mutual termination is forbidden (`ERR_TERMINATION_NOT_ALLOWED`), and the only escape is no-cure termination with `reason` set to `NO_CURE`, which is itself lawful only on a `NO_CURE_NO_PAY` contract — attempting no-cure on a `FIXED_PRICE` contract is rejected with `ERR_NO_CURE_REQUIRES_NCNP`. Termination is not available at all from `PERFORMANCE_COMPLETE` or `AWARD_FINAL` (also `ERR_TERMINATION_NOT_ALLOWED`). A no-cure termination sets `terminate_reason` to `NO_CURE`, increments the contract's `version`, and fires the termination cascade: every operation phase in `PLANNED`, `ACTIVE`, `WEATHER_HOLD`, or `ENV_SUSPENDED` moves to `ABORTED`; every charter of the casualty in `ON_HIRE`, `STANDBY_WEATHER`, or `STANDBY_ENV` is taken to `OFF_HIRE` with its charter cost computed at the current logical clock, while charters still `BOOKED` move to `CANCELLED`; the casualty's recovered property lots become disposition-eligible, the termination overriding the operations-complete gate; and no salvage award can ever be created for the contract, because award computation requires `PERFORMANCE_COMPLETE` — no cure, no pay.

### 3.4. Security Lodgement, Disbursement, and Activation Gates

Once a contract is `SIGNED`, the `ContractsOfficer` lodges security against it by posting the `contract_id` and a positive `lodged_amount_cents`. The deposit opens in `LODGED` with `held_cents` equal to the lodged amount and both `released_cents` and `applied_cents` at zero; the lodged figure is immutable thereafter, and the conservation invariant of §2.6 binds every later movement. Securities are listed with filters on `contract_id` and `status`.

Activation is the moment a signed contract becomes operable, and it is guarded by two gates evaluated in the pipeline order — safety before fiscal. The safety gate: if the latest `APPROVED` assessment of the casualty carries `pollution_risk_tier` `TIER_3`, a permit of `agency_type` `ENV_AGENCY` in status `GRANTED` must exist for the casualty, or activation is rejected with `ERR_ENV_CLEARANCE_REQUIRED`. The fiscal gate: some deposit of the contract must hold `held_cents` of at least the contract's `security_required_cents` — exact equality passes — or activation is rejected with `ERR_SECURITY_INSUFFICIENT`. Passing both moves the contract from `SIGNED` to `ACTIVE` and increments its `version`.

Disbursement moves money out of `held_cents` under one of two modes supplied in `mode`, with the amount in `amount_cents`. A `RELEASE` returns funds to the owner and is allowed only when the contract is `SETTLED` or `TERMINATED`; an `APPLY_TO_AWARD` directs funds toward award payment and is allowed only when the contract's salvage award has reached `PAID`. Either mode attempted outside its lawful state is rejected with `ERR_SECURITY_DISBURSE_NOT_ALLOWED`. The amount may not exceed the current `held_cents` — a disbursement that would drive `held_cents` negative is rejected with `ERR_SECURITY_DISBURSE_EXCEEDS_HELD`. A disbursement smaller than the held balance leaves the deposit in `PARTIALLY_DISBURSED` (from either `LODGED` or a previous `PARTIALLY_DISBURSED`), moving the amount into `released_cents` or `applied_cents` according to the mode; a disbursement exactly equal to the held balance zeroes `held_cents`, credits the mode's bucket, and closes the deposit in `CLOSED`. Each disbursement increments the deposit's `version`.

### 3.5. Permits and Agency Coordination

Agency coordination belongs to the `EnvironmentalOfficer`, who files a permit request with the `casualty_id`, the `agency_type` — `COAST_GUARD`, `PORT_AUTHORITY`, or `ENV_AGENCY` — and an inclusive validity interval from `valid_from` to `valid_to`, where the end must be strictly later than the start. The request opens in `REQUESTED`, and permits are listed with filters on `casualty_id`, `agency_type`, and `status`.

The agency-side lifecycle is cyclic where the real world is. Granting moves a permit from `REQUESTED` to `GRANTED`; suspension moves it from `GRANTED` to `SUSPENDED`; reinstatement returns it from `SUSPENDED` to `GRANTED`, and the grant–suspend loop may repeat as agencies revisit conditions. Revocation is final: a permit in `GRANTED` or `SUSPENDED` may move to `REVOKED`, which is terminal. Independently of any officer action, the clock sweep of §2.4 expires permits: any permit still in `REQUESTED`, `GRANTED`, or `SUSPENDED` whose `valid_to` has been passed by the logical clock transitions to `EXPIRED`, which is likewise terminal.

Permits become operational gates at phase activation, where the required agencies depend on the phase type: `MOBILIZATION` requires a `PORT_AUTHORITY` permit; `LIGHTERING` requires both `COAST_GUARD` and `ENV_AGENCY`; `REFLOAT` requires `COAST_GUARD`; `TOWAGE` requires `COAST_GUARD`; `WRECK_REMOVAL` requires both `COAST_GUARD` and `ENV_AGENCY`; and `DEMOBILIZATION` requires `PORT_AUTHORITY`. For each required agency, a permit of that type in `GRANTED` status must exist for the casualty — its absence is `ERR_PERMIT_MISSING` — and the permit must cover the whole planned execution: `valid_from` no later than the current logical time and `valid_to` no earlier than the current time plus the phase's `planned_duration_hours`, otherwise `ERR_PERMIT_NOT_VALID`. A permit swept to `EXPIRED` by the clock fails this validity check like any other out-of-window permit.

### 3.6. Equipment, Weather Windows, and Running the Operation

The `OperationsDirector` maintains the contractor's equipment registry. Registering an asset records its `asset_class` (`TUG`, `CRANE_BARGE`, `PONTOON`, or `OIL_RESPONSE`), a positive `day_rate_cents` hire rate, and a positive `max_hs_meters` — the maximum significant wave height the asset can operate in, compared inclusively so that a forecast exactly equal to the limit passes. New assets open `AVAILABLE`; the status is derived, moving to `CHARTERED` the moment a charter referencing the asset enters `BOOKED`, and back to `AVAILABLE` when no charter of the asset remains in `BOOKED`, `ON_HIRE`, `STANDBY_WEATHER`, or `STANDBY_ENV`. Assets are listed with filters on `asset_class` and `status`.

Weather intelligence is registered by a `SalvageMaster` as forecast windows against a casualty: `casualty_id`, an inclusive-start `window_start`, a `window_end` strictly later than the start, and a non-negative `forecast_hs_meters`. A window opens `OPEN` and is swept to `EXPIRED` — terminally — when the logical clock passes its `window_end`. Windows are listed with filters on `casualty_id` and `status`.

Booking a charter is how equipment meets the casualty. A `SalvageMaster` books with the `casualty_id`, the `equipment_asset_id`, a booked interval from `window_start` to `window_end` (end strictly after start), a `purpose` of `SALVAGE` or `POLLUTION_RESPONSE`, and — required exactly for response work — the `pollution_event_id`. Booking requires the casualty's contract to be in `SIGNED`, `ACTIVE`, or `PERFORMANCE_COMPLETE`, otherwise `ERR_CONTRACT_NOT_ACTIVE`; and the asset's class must appear among the contract plan's `required_equipment_classes`, otherwise `ERR_ASSET_CLASS_NOT_REQUIRED`. The booked interval is half-open — it includes its start and excludes its end — so two charters on the same asset whose windows merely touch at an endpoint coexist legally, while any true overlap with another charter of that asset in `BOOKED`, `ON_HIRE`, `STANDBY_WEATHER`, or `STANDBY_ENV` is rejected with `ERR_CHARTER_OVERLAP`. A new charter opens in `BOOKED`, flips its asset to `CHARTERED`, and — when the purpose is `POLLUTION_RESPONSE` — immediately refreshes the linked event's `provisional_exposure_cents` as described in §3.7. Charters are listed with filters on `casualty_id`, `equipment_asset_id`, `pollution_event_id`, and `status`.

Bringing a charter on hire is a `SalvageMaster` action with two preconditions: the casualty's non-terminal contract must be in `ACTIVE` or `PERFORMANCE_COMPLETE` (`ERR_CONTRACT_NOT_ACTIVE`), and the logical clock must sit inside the booked window — at or after `window_start` and strictly before `window_end` — otherwise `ERR_CHARTER_WINDOW_NOT_OPEN`. Going on hire stamps `on_hire_at` with the current logical time and increments the charter's `version`. Thereafter the charter may be stood down: when a phase it is linked to enters `WEATHER_HOLD`, the charter cascades from `ON_HIRE` to `STANDBY_WEATHER`; when a linked phase is environmentally suspended under cascade A, the charter moves from `ON_HIRE` to `STANDBY_ENV`. Either move opens a standby accrual interval at the current logical clock, and the corresponding resume returns the charter to `ON_HIRE`, adding the whole hours since the interval opened — fractional hours discarded — into `standby_hours`.

Taking a charter off hire, from `ON_HIRE`, `STANDBY_WEATHER`, or `STANDBY_ENV`, is the settlement point of the equipment ledger. The action stamps `off_hire_at` with the current logical clock, closes any open standby interval into `standby_hours`, and computes the day buckets and cost. Booked hours are the whole hours of the booked window; elapsed hours are the whole hours between `on_hire_at` and `off_hire_at`. Demurrage hours are the excess of elapsed over booked — zero when elapsed does not exceed booked, because the trigger is strictly-greater and an exactly-on-time charter earns no demurrage. Active hours are the elapsed hours with standby and demurrage hours removed. Each bucket is converted to days by dividing by twenty-four and rounding half up, yielding `demurrage_days`, `standby_days`, and `active_days`. The charter's `total_cost_cents` then sums three rate lines under the pinned rounding order of §2.6: the active line is `active_days` times the asset's daily rate rounded to integer cents; the standby line is `standby_days` times half the daily rate, the halved rate rounded half up to integer cents before multiplication; the demurrage line is `demurrage_days` times one and a half times the daily rate, the uplifted rate rounded half up to integer cents before multiplication. Off-hire also recomputes the contract's `cost_to_date_cents` as the sum of `total_cost_cents` over all of the casualty's charters in `OFF_HIRE`, re-evaluates the contract's `overrun_flag`, re-derives the asset's status, and — for response charters — refreshes the exposure inputs of the linked pollution event.

The `overrun_flag` is a fixed-price early-warning device: on a `FIXED_PRICE` contract it becomes true exactly when `cost_to_date_cents` exceeds the `fixed_price_cents` grown by ten percent — the threshold itself rounded half up to integer cents — with the comparison strict, so costs exactly at the threshold do not set the flag; on a `NO_CURE_NO_PAY` contract the flag is always false.

Operation phases structure the work under a contract. A `SalvageMaster` creates a phase under an `ACTIVE` contract (`ERR_CONTRACT_NOT_ACTIVE` otherwise) with the `contract_id`, a `phase_type` of `MOBILIZATION`, `LIGHTERING`, `REFLOAT`, `TOWAGE`, `WRECK_REMOVAL`, or `DEMOBILIZATION`, and a positive `planned_duration_hours`; the phase opens in `PLANNED`, and phases are listed with filters on `contract_id` and `status`. Activation commits the phase to a forecast and a fleet: the request names a `weather_window_id` and a non-empty list of `charter_ids`. Activation evaluates its gates in the pipeline order of §2.7. The environmental gate rejects with `ERR_ENV_HOLD_ACTIVE` when the casualty's `env_posture` is `ENV_HOLD`. The weather gate requires the named window to be `OPEN`; requires the window's `forecast_hs_meters` not to exceed the smallest `max_hs_meters` among the assets of the attached charters — an inclusive boundary, so a forecast exactly equal to the limit passes, and exceeding it yields `ERR_WEATHER_LIMIT_EXCEEDED`; and requires the plan to fit inside the window with a six-hour buffer at both ends — activation no earlier than six hours after the window's start, and the current time plus `planned_duration_hours` no later than six hours before the window's end, with equality at both buffer edges passing and any violation raising `ERR_WEATHER_WINDOW_INFEASIBLE`. The permit gate applies the agency map of §3.5, raising `ERR_PERMIT_MISSING` or `ERR_PERMIT_NOT_VALID`. The charter linkage gate requires `charter_ids` to be non-empty (`ERR_INVALID_REQUEST`), every referenced charter to exist (`ERR_NOT_FOUND`), and each to belong to this casualty and be in `ON_HIRE` (`ERR_INVALID_STATE_TRANSITION`). Successful activation moves the phase from `PLANNED` to `ACTIVE`, stamps `activated_at` with the logical clock, stores the `weather_window_id` and `charter_ids` on the phase, writes the phase's identity into each charter's `linked_phase_id`, and — on the first activation of the contract — lifts the casualty from `CONTRACTED` to `IN_OPERATION`.

Once running, a phase breathes with conditions. A `SalvageMaster` may move an `ACTIVE` phase to `WEATHER_HOLD`, which cascades its linked on-hire charters into `STANDBY_WEATHER`; resuming from `WEATHER_HOLD` — or from `ENV_SUSPENDED` — is permitted only while the casualty's `env_posture` is not `ENV_HOLD` (`ERR_ENV_HOLD_ACTIVE`) and returns linked standby charters to `ON_HIRE`. The hold–resume loop is unbounded. An `ACTIVE` phase completes on the master's completion action, and that completion fires cascade B of §2.10: when the completing phase leaves every phase of the contract in a terminal state — `COMPLETE` or `ABORTED` — with at least one phase existing, the contract moves from `ACTIVE` to `PERFORMANCE_COMPLETE` and the casualty moves on to `OPERATIONS_COMPLETE`. Phases in `PLANNED`, `ACTIVE`, `WEATHER_HOLD`, or `ENV_SUSPENDED` move to `ABORTED` under the termination cascade of §3.3.

### 3.7. Pollution Events and Special Compensation

Pollution is tracked per casualty by the `EnvironmentalOfficer`, who reports an event with the `casualty_id`, the `pollutant_class` — `OIL_PERSISTENT`, `OIL_NON_PERSISTENT`, `CHEMICAL`, or `DEBRIS` — the initial `tier` (`TIER_1`, `TIER_2`, or `TIER_3`), and a non-negative estimated release volume `est_volume_m3`. The event opens in `REPORTED`, and its creation immediately recomputes the casualty's environmental posture. Events are listed with filters on `casualty_id` and `status`.

The posture derivation is a pure function of the casualty's open events — those in `REPORTED`, `ESCALATED`, or `CONTAINED`, containment still counting as open. If any open event carries tier `TIER_2` or `TIER_3`, the posture is `ENV_HOLD`; otherwise, if any open event carries `TIER_1`, the posture is `ENV_WATCH`; otherwise it is `ENV_CLEAR`. Entering `ENV_HOLD` fires cascade A: every `ACTIVE` phase of the casualty's contracts moves to `ENV_SUSPENDED`, and each suspended phase pushes its linked on-hire charters to `STANDBY_ENV`. Leaving the hold is deliberately asymmetric: only verify-clean relaxes the posture, and when the posture falls back to `ENV_WATCH` or `ENV_CLEAR`, suspended phases stay `ENV_SUSPENDED` — resumption is always the master's deliberate act, never automatic. Containment alone never relaxes anything.

Escalation raises the stakes: the officer supplies a `new_tier` that must be strictly higher than the event's current tier — anything else is rejected with `ERR_POLLUTION_TIER_NOT_RAISED` — moving the event from `REPORTED` or `CONTAINED` to `ESCALATED`, updating its `tier`, and recomputing the posture with the full cascade. An event can therefore re-enter `ESCALATED` after containment. Containment moves an event from `REPORTED` or `ESCALATED` to `CONTAINED` and recomputes the posture, which by the rule above does not relax. Verification of clean-up, from `CONTAINED`, moves the event to its terminal `VERIFIED_CLEAN`, computes the event's `final_exposure_cents`, refreshes `special_compensation_payable_cents`, and recomputes the posture.

Special compensation is accounted in two variants over the response set — the charters of the same casualty whose `purpose` is `POLLUTION_RESPONSE` and whose `pollution_event_id` names this event; `SALVAGE` charters never contribute. The provisional, tariff-based variant runs while the response is mobilizing: whenever a response charter is booked, the event's `provisional_exposure_cents` becomes the sum, across the whole response set regardless of charter status, of each charter's uplifted daily rate — the asset's `day_rate_cents` multiplied by 1.25 and rounded half up to integer cents — multiplied by the charter's booked days. This variant ignores actual days, standby, demurrage, and pollutant class. The final, actual-cost variant runs at verify-clean over the response charters that have reached `OFF_HIRE`: the sum of their `total_cost_cents` is multiplied by the pollutant multiplier — 1.5 for `OIL_PERSISTENT`, 1.2 for `OIL_NON_PERSISTENT`, 1.8 for `CHEMICAL`, and 1.0 for `DEBRIS` — and the product is rounded half up to integer cents to become `final_exposure_cents`. The two variants share a charter set but diverge whenever actual usage deviates from the booking.

Netting turns exposure into a payable amount, under a pinned evaluation order: charter costs are computed at each off-hire first, the final salvage award is computed second, and only then is special compensation netted — netting before the award exists is undefined. When the contract's `scopic_clause_included` is true and a salvage award exists, `special_compensation_payable_cents` is the final exposure minus the award's `computed_amount_cents`, floored at zero; otherwise it is simply the `final_exposure_cents`. Whenever the award's `computed_amount_cents` is computed or recomputed while a final exposure exists, the payable is re-netted on that basis.

### 3.8. Recovered Property, Liens, and Disposition

As the operation recovers material, a `SalvageMaster` logs each salved lot against the casualty — an action lawful only while the casualty's contract is `ACTIVE` or `PERFORMANCE_COMPLETE`, otherwise `ERR_CONTRACT_NOT_ACTIVE` — supplying the `casualty_id`, a `property_type` of `BUNKERS`, `CARGO`, `VESSEL_HULL`, or `WRECK_DEBRIS`, a positive `quantity_tonnes`, and a non-negative `declared_value_cents`. A new lot opens with `custody_status` `SALVED`, `documentation_status` `PENDING_SURVEY`, its `in_custody_tonnes` initialized to the full `quantity_tonnes`, its three disposition buckets `redelivered_tonnes`, `sold_tonnes`, and `disposed_tonnes` at zero, and its `lien_amount_cents` at zero. Lots are listed with filters on `casualty_id`, `custody_status`, and `storage_site_id`.

Storage capacity is managed through sites that the `OperationsDirector` registers with a `name` and a positive aggregate `capacity_tonnes`; a site's `allocated_tonnes` is always the sum of `quantity_tonnes` over the lots naming that site in `storage_site_id` whose custody is `SECURED_ASHORE` or `LIENED`. Moving a salved lot ashore — the master's secure-ashore action carrying the target `storage_site_id` — is an aggregate capacity check: the site's `allocated_tonnes` plus the lot's `quantity_tonnes` must not exceed `capacity_tonnes`, exact equality passes, and overflow is rejected with `ERR_STORAGE_CAPACITY_EXCEEDED`. Securing sets the lot's `storage_site_id`, moves custody from `SALVED` to `SECURED_ASHORE`, and recomputes the site's `allocated_tonnes`.

Valuation proceeds on the documentation dimension, which evolves in parallel with custody. A `MarineSurveyor` surveys the lot, supplying the `verified_value_cents`; the survey stamps `surveyor_id` with the acting surveyor's identity and moves `documentation_status` from `PENDING_SURVEY` to `SURVEYED`. Verification by an `OperationsDirector` then moves it from `SURVEYED` to `VALUE_VERIFIED` — terminal — under the segregation-of-duties rule that the verifier must differ from the recorded `surveyor_id` (`ERR_SOD_VIOLATION`). The casualty's total verified salved value is, at any moment, the sum of `verified_value_cents` over its lots in `VALUE_VERIFIED`; lots still in `PENDING_SURVEY` or `SURVEYED` contribute nothing.

Liens are the contractor's security over salved property. A `ContractsOfficer` may assert a lien over a lot in `SECURED_ASHORE` while the casualty's `lifecycle_status` is `IN_OPERATION` or `OPERATIONS_COMPLETE` — outside those states the attempt meets `ERR_INVALID_STATE_TRANSITION` — supplying the `lien_amount_cents`; custody moves to `LIENED` with the amount recorded. When the casualty's contract award is later marked paid, every liened lot of the casualty is released automatically: `lien_amount_cents` returns to zero and custody falls back from `LIENED` to `SECURED_ASHORE`.

Disposition is the mass-accounted exit, performed by a `SalvageMaster` through the dispose action with a `method` of `REDELIVER`, `SELL`, or `SCRAP` and a `tonnes` amount. Three gates apply by branch. All branches require the lot to be disposition-eligible — the casualty in `OPERATIONS_COMPLETE`, or the contract `TERMINATED` — and tonnage within reach: `tonnes` greater than the lot's `in_custody_tonnes` is rejected with `ERR_QUANTITY_EXCEEDS_REMAINING`. Redelivery requires `documentation_status` `VALUE_VERIFIED` and is only defined from `SECURED_ASHORE`; attempting it while the lot is liened meets `ERR_LIEN_ACTIVE`. An ordinary sale from `SECURED_ASHORE` requires `VALUE_VERIFIED` and requires the casualty's contract award to be `PAID` — the lien satisfied — otherwise `ERR_LIEN_ACTIVE`; a lien sale from `LIENED` is lawful only when the contract is `TERMINATED`, otherwise `ERR_LIEN_ACTIVE`, and likewise requires `VALUE_VERIFIED`. Scrapping requires the documentation to be `SURVEYED` or `VALUE_VERIFIED`. Each disposition credits the method's bucket — `redelivered_tonnes`, `sold_tonnes`, or `disposed_tonnes` — and draws `in_custody_tonnes` down by the same amount, preserving the mass invariant of §2.6. A partial disposition leaves custody in `SECURED_ASHORE`; the lot reaches terminal custody exactly when a dispose call zeroes `in_custody_tonnes`, and the terminal state takes the method of that zeroing call — `REDELIVERED`, `SOLD`, or `DISPOSED` respectively. A terminal lien sale also zeroes `lien_amount_cents`, and any terminal disposition recomputes the site's `allocated_tonnes`.

### 3.9. Award, Arbitration, Settlement, and the Insurer Documentation Pack

Once operations are complete, the commercial endgame begins. A `ContractsOfficer` creates the contract's salvage award — one award per contract, a second attempt rejected with `ERR_AWARD_ALREADY_EXISTS` — which requires the contract to be in `PERFORMANCE_COMPLETE` (`ERR_CONTRACT_NOT_ACTIVE` otherwise) and every recovered lot of the casualty to be `VALUE_VERIFIED`, a single unverified lot blocking computation with `ERR_PROPERTIES_NOT_VERIFIED`. The award opens in `COMPUTED` with `computed_amount_cents` set by the final award calculation, and its computation re-nets special compensation on any event whose final exposure already exists. Awards are listed with filters on `contract_id` and `status`.

The final calculation differs sharply from the provisional of §3.3. For a `FIXED_PRICE` contract, `computed_amount_cents` is the `fixed_price_cents`. For `NO_CURE_NO_PAY`, let the verified value be the sum of `verified_value_cents` over the casualty's lots in `VALUE_VERIFIED`. The base award is tiered against that verified value in exact rational arithmetic: ten percent of the portion up to one hundred million cents, plus eight percent of the portion between one hundred million and five hundred million cents, plus six percent of any portion above five hundred million cents. The base is then enhanced by two additive multipliers: a risk addition keyed to the casualty's `casualty_type` — five percent for `GROUNDING`, eight percent for `COLLISION`, ten percent for `FIRE`, fifteen percent for `SUNK` — and an environment addition keyed to the highest `tier` over all pollution events of the casualty regardless of their status — five percent for `TIER_1`, ten percent for `TIER_2`, twenty percent for `TIER_3`, and zero when the casualty has no events. The enhanced figure is the base multiplied by one plus both additions, rounded half up to integer cents in a single rounding, and the final `computed_amount_cents` is the lesser of the enhanced figure and the verified value — the cap applied after rounding. On identical declared-versus-verified data the final figure still diverges from the provisional one, because twelve percent flat is not the tiered-and-multiplied schedule.

Resolution proceeds by agreement or arbitration. The `ContractsOfficer` may record a party-agreed amount in `agreed_amount_cents`, moving the award from `COMPUTED` to `AGREED`; or refer the award to arbitration, moving it from `COMPUTED` to `IN_ARBITRATION` — a referral lawful only when every lot of the casualty sits in terminal custody (`REDELIVERED`, `SOLD`, or `DISPOSED`), otherwise `ERR_PROPERTIES_NOT_DISPOSED`. In arbitration the `Arbitrator` publishes an award by supplying `awarded_amount_cents`, moving the award from `IN_ARBITRATION` to `AWARDED`. The `ContractsOfficer` may appeal with the stated `grounds`, moving the award from `AWARDED` to `APPEALED` and incrementing `appeal_count` by 1; a further arbitral decision returns the award from `APPEALED` to `AWARDED`, overwriting `awarded_amount_cents` with the new decision, and this appeal loop may repeat. Payment is recorded by the `ContractsOfficer` from either `AGREED` or `AWARDED`: `paid_amount_cents` takes the `agreed_amount_cents` when paid from agreement and the `awarded_amount_cents` when paid from arbitration; the award moves to its terminal `PAID`, the contract automatically advances from `PERFORMANCE_COMPLETE` to `AWARD_FINAL`, and every liened lot of the casualty is released as described in §3.8.

Documentation runs in parallel, because settlement depends on it. A `SalvageMaster` opens an insurer documentation pack against a contract in `ACTIVE`, `PERFORMANCE_COMPLETE`, or `AWARD_FINAL` — any other contract state is rejected with `ERR_CONTRACT_NOT_ACTIVE` — with the `contract_id`; at most one pack per contract may be open, meaning not yet `ACCEPTED`, and a duplicate attempt meets `ERR_DUPLICATE_OPEN_DOC_PACK`. The pack opens in `COMPILING` and is listed with filters on `contract_id` and `status`. Into it the master appends documentation entries, each carrying the pack's `doc_pack_id`, an `entry_type` of `DAILY_LOG`, `COST_LOG`, `POLLUTION_REPORT`, or `SURVEY_REPORT`, a `ref_id` pointing at the documented record, the documented `entry_date`, and a free-text `summary`. The `ref_id` is a plain reference value rather than a foreign key constraint, but it is type-checked: a `DAILY_LOG` must reference an operation phase, a `COST_LOG` an equipment charter, a `POLLUTION_REPORT` a pollution event, and a `SURVEY_REPORT` a recovered property lot — all of the same casualty, and the referenced record must be in the qualifying state for its type — the same per-type qualification that the completeness rules below use to build the required set. A missing reference, a wrong entity type, a wrong casualty, or an unqualified record state is rejected with `ERR_DOC_ENTRY_INVALID`. Entries are immutable once appended and carry only `id` and `created_at` (§2.5).

Completeness is evaluated live on every entry append and again at submission. The required set is derived from the casualty behind the pack's contract: one `DAILY_LOG` per operation phase of the contract that was ever activated — status in `ACTIVE`, `WEATHER_HOLD`, `ENV_SUSPENDED`, `COMPLETE`, or `ABORTED` with `activated_at` set; one `COST_LOG` per charter of the casualty in `OFF_HIRE`; one `POLLUTION_REPORT` per pollution event of the casualty in any status; and one `SURVEY_REPORT` per recovered lot of the casualty whose documentation is `SURVEYED` or `VALUE_VERIFIED`. The `required_count` and `satisfied_count` record the last evaluation, a requirement being satisfied when at least one entry of the matching `entry_type` and `ref_id` covers it, and `completeness_pct` is one hundred times the satisfied count divided by the required count — reading 0 when nothing is required. Submission by a `SalvageMaster` is a fiscal documentation gate: the completeness must read exactly 100 — three of four requirements reads 75 and fails — otherwise `ERR_DOC_INCOMPLETE`; at submission the three counters freeze at their evaluated values and the pack moves from `COMPILING` to `SUBMITTED`.

Review belongs to the `InsurerSurveyor`, who records an `outcome` and optional `notes`. An `ACCEPT` outcome moves the pack to its terminal `ACCEPTED`; a `DEFICIENT` outcome returns the pack to `COMPILING` for rework, and the submit–review loop may repeat; either way the reviewer's notes are stored in `review_notes`.

Settlement closes the commercial file: the `ContractsOfficer` settles a contract in `AWARD_FINAL`, which requires every security deposit of the contract to be `CLOSED` (an open deposit blocks settlement with `ERR_SECURITY_DISBURSE_NOT_ALLOWED`) and every documentation pack of the contract to be `ACCEPTED` (`ERR_DOCS_NOT_ACCEPTED`). Settlement moves the contract to its terminal `SETTLED`. The casualty file itself closes last: the `OperationsDirector` closes a casualty in `OPERATIONS_COMPLETE`, which requires every contract of the casualty to be `SETTLED` or `TERMINATED` and no pollution event of the casualty to remain in `REPORTED`, `ESCALATED`, or `CONTAINED` — either failure blocks closure with `ERR_CASUALTY_NOT_CLOSABLE`. A closed casualty is terminal in `CLOSED`.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code — this covers reporting a casualty, submitting an assessment, drafting a plan, creating a contract, lodging a security, filing a permit, registering an asset or storage site, booking a charter, registering a weather window, creating a phase, reporting a pollution event, logging a property lot, creating a salvage award, opening a documentation pack, and appending a documentation entry. Operations that act on an existing resource — every state transition, review, disbursement, disposition, sweep-driving clock set, and the like — return `200 OK`. All list and single-resource reads return `200 OK`. Endpoints marked "All roles" accept any of the seven declared roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock; sweeps expired permits and weather windows | All roles |
| POST | `/casualties` | Report a new casualty | SalvageMaster |
| GET | `/casualties` | List casualties with filters | All roles |
| GET | `/casualties/{casualty_id}` | Get one casualty | All roles |
| POST | `/casualties/{casualty_id}/close` | Close a casualty file (terminal) | OperationsDirector |
| POST | `/assessments` | Submit an incident assessment (supersedes siblings; OCC on casualty version) | MarineSurveyor |
| GET | `/assessments` | List assessments, filterable by casualty and status | All roles |
| GET | `/assessments/{assessment_id}` | Get one assessment | All roles |
| POST | `/assessments/{assessment_id}/approve` | Approve an assessment (SoD vs assessor) | OperationsDirector |
| POST | `/assessments/{assessment_id}/reject` | Reject an assessment (SoD vs assessor) | OperationsDirector |
| POST | `/plans` | Draft a salvage plan | SalvageMaster |
| GET | `/plans` | List plans, filterable by casualty and status | All roles |
| GET | `/plans/{plan_id}` | Get one plan | All roles |
| POST | `/plans/{plan_id}/submit` | Submit a plan for approval | SalvageMaster |
| POST | `/plans/{plan_id}/approve` | Approve a plan (SoD vs drafter; requires approved assessment) | OperationsDirector |
| POST | `/plans/{plan_id}/reject` | Reject a plan back to draft (revision loop) | OperationsDirector |
| POST | `/contracts` | Create a salvage contract in draft (one non-terminal contract per casualty) | ContractsOfficer |
| GET | `/contracts` | List contracts, filterable by casualty, plan, and status | All roles |
| GET | `/contracts/{contract_id}` | Get one contract | All roles |
| POST | `/contracts/{contract_id}/offer` | Issue the opening offer (round 1) | ContractsOfficer |
| POST | `/contracts/{contract_id}/counter` | Counter-offer within the negotiation cycle (OCC on contract version) | ContractsOfficer |
| POST | `/contracts/{contract_id}/sign` | Sign the contract; computes provisional award and security requirement | ContractsOfficer |
| POST | `/contracts/{contract_id}/activate` | Activate a signed contract (safety gate before fiscal gate) | ContractsOfficer |
| POST | `/contracts/{contract_id}/terminate` | Terminate: mutual pre-activation; no-cure from active on no-cure-no-pay only | ContractsOfficer |
| POST | `/contracts/{contract_id}/settle` | Settle after award final (requires closed securities and accepted doc packs) | ContractsOfficer |
| POST | `/securities` | Lodge a security deposit against a signed contract | ContractsOfficer |
| GET | `/securities` | List security deposits, filterable by contract and status | All roles |
| GET | `/securities/{security_id}` | Get one security deposit | All roles |
| POST | `/securities/{security_id}/disburse` | Disburse held funds: release to owner or apply to award | ContractsOfficer |
| POST | `/permits` | File a permit request with an agency | EnvironmentalOfficer |
| GET | `/permits` | List permits, filterable by casualty, agency, and status | All roles |
| GET | `/permits/{permit_id}` | Get one permit | All roles |
| POST | `/permits/{permit_id}/grant` | Grant a requested permit | EnvironmentalOfficer |
| POST | `/permits/{permit_id}/suspend` | Suspend a granted permit | EnvironmentalOfficer |
| POST | `/permits/{permit_id}/reinstate` | Reinstate a suspended permit | EnvironmentalOfficer |
| POST | `/permits/{permit_id}/revoke` | Revoke a permit (terminal) | EnvironmentalOfficer |
| POST | `/equipment-assets` | Register a contractor equipment asset | OperationsDirector |
| GET | `/equipment-assets` | List equipment assets, filterable by class and status | All roles |
| GET | `/equipment-assets/{asset_id}` | Get one equipment asset | All roles |
| POST | `/charters` | Book an equipment charter window (half-open; adjacent allowed, overlap rejected) | SalvageMaster |
| GET | `/charters` | List charters, filterable by casualty, asset, pollution event, and status | All roles |
| GET | `/charters/{charter_id}` | Get one charter | All roles |
| POST | `/charters/{charter_id}/on-hire` | Bring a booked charter on hire at the logical clock | SalvageMaster |
| POST | `/charters/{charter_id}/off-hire` | Take a charter off hire; computes day buckets, cost, and contract exposure | SalvageMaster |
| POST | `/weather-windows` | Register a forecast weather window for a casualty site | SalvageMaster |
| GET | `/weather-windows` | List weather windows, filterable by casualty and status | All roles |
| GET | `/weather-windows/{window_id}` | Get one weather window | All roles |
| POST | `/phases` | Create an operation phase under an active contract | SalvageMaster |
| GET | `/phases` | List phases, filterable by contract and status | All roles |
| GET | `/phases/{phase_id}` | Get one phase | All roles |
| POST | `/phases/{phase_id}/activate` | Activate a phase inside a weather window with attached charters | SalvageMaster |
| POST | `/phases/{phase_id}/hold-weather` | Suspend an active phase for weather (linked charters to weather standby) | SalvageMaster |
| POST | `/phases/{phase_id}/resume` | Resume a phase from weather hold or environmental suspension | SalvageMaster |
| POST | `/phases/{phase_id}/complete` | Complete an active phase; last terminal phase bubbles the contract upward | SalvageMaster |
| POST | `/pollution-events` | Report a pollution event for a casualty | EnvironmentalOfficer |
| GET | `/pollution-events` | List pollution events, filterable by casualty and status | All roles |
| GET | `/pollution-events/{event_id}` | Get one pollution event | All roles |
| POST | `/pollution-events/{event_id}/escalate` | Escalate an event to a strictly higher tier (environmental cascade) | EnvironmentalOfficer |
| POST | `/pollution-events/{event_id}/contain` | Mark an event contained (posture does not relax on contain alone) | EnvironmentalOfficer |
| POST | `/pollution-events/{event_id}/verify-clean` | Verify clean-up; computes final exposure and special-compensation netting | EnvironmentalOfficer |
| POST | `/properties` | Log a salved property lot | SalvageMaster |
| GET | `/properties` | List property lots, filterable by casualty, custody, and storage site | All roles |
| GET | `/properties/{property_id}` | Get one property lot | All roles |
| POST | `/properties/{property_id}/secure-ashore` | Move a salved lot into a storage site (aggregate capacity check) | SalvageMaster |
| POST | `/properties/{property_id}/survey` | Record the surveyor's verified value | MarineSurveyor |
| POST | `/properties/{property_id}/verify-value` | Verify the surveyed value (SoD vs surveyor) | OperationsDirector |
| POST | `/properties/{property_id}/lien` | Assert a salvage lien over a secured lot | ContractsOfficer |
| POST | `/properties/{property_id}/dispose` | Partially or fully dispose of a lot (redeliver, sell, or scrap) | SalvageMaster |
| POST | `/storage-sites` | Register a storage site with aggregate capacity | OperationsDirector |
| GET | `/storage-sites` | List storage sites | All roles |
| GET | `/storage-sites/{site_id}` | Get one storage site | All roles |
| POST | `/contracts/{contract_id}/award` | Create and compute the contract's salvage award | ContractsOfficer |
| GET | `/awards` | List awards, filterable by contract and status | All roles |
| GET | `/awards/{award_id}` | Get one award | All roles |
| POST | `/awards/{award_id}/agree` | Record a party-agreed amount without arbitration | ContractsOfficer |
| POST | `/awards/{award_id}/submit-arbitration` | Refer the award to arbitration (requires all lots in terminal custody) | ContractsOfficer |
| POST | `/awards/{award_id}/decide` | Publish an arbitral award (also resolves appeals) | Arbitrator |
| POST | `/awards/{award_id}/appeal` | Appeal an arbitral award | ContractsOfficer |
| POST | `/awards/{award_id}/mark-paid` | Record payment (contract to award final; liens lift) | ContractsOfficer |
| POST | `/doc-packs` | Open an insurer documentation pack for a contract | SalvageMaster |
| GET | `/doc-packs` | List doc packs, filterable by contract and status | All roles |
| GET | `/doc-packs/{pack_id}` | Get one doc pack (with completeness fields) | All roles |
| POST | `/doc-packs/{id}/entries` | Append a documentation entry (type-checked reference into the same casualty) | SalvageMaster |
| GET | `/doc-packs/{id}/entries` | List entries of a doc pack | All roles |
| POST | `/doc-packs/{pack_id}/submit` | Submit the pack to the insurer (requires exact full completeness) | SalvageMaster |
| POST | `/doc-packs/{pack_id}/review` | Insurer review: accept (terminal) or deficient (back to compiling) | InsurerSurveyor |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_ENV_HOLD_ACTIVE` | 422 Unprocessable Entity |
| `ERR_ENV_CLEARANCE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_WEATHER_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_WEATHER_WINDOW_INFEASIBLE` | 422 Unprocessable Entity |
| `ERR_PERMIT_MISSING` | 422 Unprocessable Entity |
| `ERR_PERMIT_NOT_VALID` | 422 Unprocessable Entity |
| `ERR_CHARTER_OVERLAP` | 409 Conflict |
| `ERR_CHARTER_WINDOW_NOT_OPEN` | 422 Unprocessable Entity |
| `ERR_STORAGE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_ASSESSMENT_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_PLAN_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_CONTRACT_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_PROPERTIES_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_PROPERTIES_NOT_DISPOSED` | 422 Unprocessable Entity |
| `ERR_LIEN_ACTIVE` | 422 Unprocessable Entity |
| `ERR_ASSET_CLASS_NOT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ACTIVE_CONTRACT` | 409 Conflict |
| `ERR_DUPLICATE_OPEN_DOC_PACK` | 409 Conflict |
| `ERR_AWARD_ALREADY_EXISTS` | 409 Conflict |
| `ERR_QUANTITY_EXCEEDS_REMAINING` | 422 Unprocessable Entity |
| `ERR_POLLUTION_TIER_NOT_RAISED` | 422 Unprocessable Entity |
| `ERR_DOC_ENTRY_INVALID` | 422 Unprocessable Entity |
| `ERR_DOC_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_TERMINATION_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_NO_CURE_REQUIRES_NCNP` | 422 Unprocessable Entity |
| `ERR_CASUALTY_NOT_CLOSABLE` | 422 Unprocessable Entity |
| `ERR_DOCS_NOT_ACCEPTED` | 422 Unprocessable Entity |
| `ERR_SECURITY_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_SECURITY_DISBURSE_EXCEEDS_HELD` | 422 Unprocessable Entity |
| `ERR_SECURITY_DISBURSE_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_STALE_CONTRACT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CASUALTY_VERSION` | 412 Precondition Failed |
