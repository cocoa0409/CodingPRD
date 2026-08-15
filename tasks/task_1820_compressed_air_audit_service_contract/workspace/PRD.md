# Compressed Air Audit Service API — Product Requirements Document

## 1. Introduction

Compressed air is among the most expensive utilities in an industrial plant, and most of that expense is invisible: leaks bleed capacity around the clock, dryers and filters drift past their service intervals, and compressors run sequenced for yesterday's demand. This document specifies the Compressed Air Audit Service API, the system of record for a compressed-air equipment dealer's audit-and-service business. The platform covers the full commercial arc of an engagement — baseline demand profiling and leak surveys, repair prioritization ranked by CFM loss, dryer and filter maintenance intervals tracked against compressor run-hours, energy-savings engineering with utility rebate filing, compressor sequencing and control retrofits, tiered service contracts with response-time SLAs, rental compressors during outages, and savings guarantees whose settlement survives measurement disputes.

The API serves two organizations at once. Dealer-side staff — platform administrators, energy engineers, field service technicians, and contract managers — drive the audit, engineering, and commercial workflows, while a customer-side facility manager authorizes repairs, approves retrofits, calls in service tickets, reserves rental units, and disputes guarantee measurements. Resources are organized as peer collections that reference a customer facility, and every consequential write propagates its effects — facility posture changes, staleness flags, escrow balances, credit accruals, supersede cascades — atomically within the triggering request, so a reader of the API always observes a consistent facility state.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID` identifies the acting user and `X-User-Role` declares their operational capacity. A request missing either header, or carrying a role value outside the declared set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes five roles with these exact spellings:

- `DealerAdmin` — dealer platform administrator; owns facility onboarding and lifecycle, the rental fleet, rebate decisions, and the logical clock.
- `EnergyEngineer` — dealer energy engineer; owns demand profiles, leak surveys and tags, savings cases, and retrofit proposals.
- `ServiceTech` — dealer field service technician; logs run-hours, works service tickets, delivers and returns rentals, services dryers and filters, and installs retrofits.
- `ContractManager` — dealer contract and commercial manager; owns service contracts, SLA credits, guarantee certificates, and rental invoicing.
- `FacilityManager` — customer-side facility manager; authorizes repairs, approves and accepts retrofits, opens tickets and rental reservations, and disputes measurements.

An attempt to perform an operation outside the caller's role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403); the authoritative role assignment per operation is the endpoint table in §4.

The two headers relate to persisted data differently per role. When `X-User-Role` is `FacilityManager`, `X-User-ID` is the `id` of the acting Facility; ownership checks on any resource that belongs to a Facility — directly, or through its parent chain such as a leak tag reached through its survey — compare the resource's owning facility to `X-User-ID`, and a mismatch is rejected with `ERR_FACILITY_OWNERSHIP_MISMATCH` (HTTP 403). When `X-User-Role` is `DealerAdmin`, `EnergyEngineer`, `ServiceTech`, or `ContractManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow calls for an actor stamp (for example `locked_by_user_id` on a demand profile, `submitted_by_user_id` and `verified_by_user_id` on a leak survey, or `repaired_by_user_id` on a leak tag) but never compares it to any entity's `id`. Segregation-of-duties rules compare two such recorded operator identifiers against each other, never entity ownership.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. In addition to pagination, each list endpoint accepts the entity-specific filters named in the workflow narratives of §3 (for example `status`, `facility_id`, or `savings_status`).

### 2.4. Common Resource Properties

Every resource in the system — Facility, Compressor, DemandProfile, LeakSurvey, LeakTag, MaintenanceSchedule, RetrofitProject, SavingsCase, ServiceContract, ServiceTicket, RentalAsset, RentalReservation, GuaranteeCertificate, and ServiceCredit — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments with every mutation of the resource, including mutations driven by cascades from other resources.

No entity in this domain is exempt: all fourteen resource types carry the full common-field set, so `updated_at` and `version` are always present.

### 2.5. The Logical Clock

The server maintains a logical clock that is decoupled from wall-clock time. At startup, before any clock-set call, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time thereafter. A `DealerAdmin`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc` value. The logical clock is the single source of truth for every time-sensitive rule in the domain: it stamps `reported_at` and `first_response_at` on service tickets, `accrued_at` on service credits, and `accepted_date` on retrofit projects, and it decides whether a contract has passed its `end_date` and whether a credit has reached its `expires_at` instant.

### 2.6. Facility Posture and the Settlement Gate

Each facility carries a computed `posture` alongside its lifecycle `status`, and posture gates the settlement of savings guarantees. A facility's posture is `OUTAGE_ACTIVE` whenever at least one of its compressors is `DOWN`; otherwise it is `MAINTENANCE_DELINQUENT` whenever at least one of its `ACTIVE` dryer or filter schedules is delinquent; otherwise it is `NORMAL`. This precedence is pinned — an outage always outranks maintenance delinquency — so a facility with both a down compressor and an overdue filter reports `OUTAGE_ACTIVE`.

Posture is not cached indifferently: it is recomputed on any compressor status change, on every run-hours logging, on maintenance schedule creation, service recording, and retirement, and on any facility status change such as suspension or reinstatement. Every posture recompute also refreshes `settlement_blocked` on each of the facility's guarantee certificates whose `settlement_status` is not `PAID`: the flag is set whenever the facility's posture is anything other than `NORMAL`, and cleared when posture returns to `NORMAL`. Certificates already `PAID` are history and are left untouched.

### 2.7. Optimistic Concurrency Control on the Facility Version

Two writes are guarded by optimistic concurrency control on the Facility, because each of them supersedes an incumbent: locking a demand profile retires the facility's previously `LOCKED` profile, and activating a service contract retires the facility's currently `ACTIVE` contract. Both writes therefore require the request body to carry `expected_facility_version`, a non-optional field holding the facility's `version` as last observed by the caller. If the facility's current `version` no longer equals the supplied value — because another lock or contract activation has advanced it since the caller last read the facility — the write is rejected with `ERR_STALE_VERSION` (HTTP 412). The rejection protects the caller from overwriting a baseline or a contract it has not observed: a lock caller's view of which profile is the current baseline would otherwise be stale, and an activate caller may not have seen the contract that is now `ACTIVE`. Endpoints other than these two do not take any version field.

### 2.8. Measurement Units, Rounding, and Monetary Precision

Energy figures are whole kilowatt-hours: every computed kWh value is rounded half-up to zero decimal places. Monetary values are integer cents throughout; where a monetary computation involves a fractional intermediate, it is rounded half-up to a whole cent. Airflow figures (`measured_avg_cfm`, `measured_peak_cfm`, `cfm_loss`, and `total_leak_cfm`) are carried at one decimal place. Rates and percentages are exact decimals — the utility rate is an integer number of cents per kWh, and factors such as the kilowatt load per CFM or the rebate percentages are applied exactly as stated in §3.

When a formula is composed of nested steps, the rounding order is part of the specification: each step's output is rounded before it feeds the next step, in exactly the order the relevant §3 narrative states, and summing unrounded intermediates and rounding once at the end is not equivalent. Calendar windows and durations count days inclusively at both ends unless stated otherwise. Dates are ISO `YYYY-MM-DD`; datetimes stamped from the logical clock are ISO 8601 UTC values at second granularity, and SLA comparisons against them are inclusive, as §3.7 states.

### 2.9. Validation Order and Request Rejection

A request that fails several rules reports exactly one error: the one from the lowest-numbered validation tier. The tiers, in evaluation order, are:

1. **Authentication context** — the `X-User-ID` and `X-User-Role` headers are present and the role is declared (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role authorization** — the role appears in the endpoint's authorized set (`ERR_FORBIDDEN_FOR_ROLE`).
3. **Path existence** — path-template resource identifiers resolve, validated left to right; the first identifier that does not resolve yields `ERR_NOT_FOUND` (HTTP 404) before any later segment is examined.
4. **Request schema and input semantics** — required fields are present, types are valid, enum values fall in their declared sets, dates are well-formed ISO values, and the domain input rules hold: `window_end_date` may not precede `window_start_date`, `target_pressure_psi` must be strictly below `baseline_pressure_psi`, and `corrected_measured_kwh` is required exactly when a dispute `outcome` is `UPHELD`. Failures here yield `ERR_INVALID_REQUEST` (HTTP 400).
5. **Facility ownership** — when the role is `FacilityManager`, the caller's `X-User-ID` must equal the owning facility's `id` (`ERR_FACILITY_OWNERSHIP_MISMATCH`).
6. **State and state-machine gates** — the requested transition must be declared for the resource's current state (or, for dual-dimension resources, the relevant dimension's current value), and the state preconditions of §3 must hold. An undeclared transition yields `ERR_INVALID_STATE_TRANSITION` (HTTP 409); named gates yield their own errors such as `ERR_FACILITY_NOT_ACTIVE` or `ERR_PROFILE_NOT_LOCKED`.
7. **Cross-facility referential integrity** — every referenced entity (baseline or post profile, retrofit project, contract, savings case, compressor) must belong to the same facility as the resource being created or acted upon; violations yield `ERR_FACILITY_MISMATCH` (HTTP 409).
8. **Temporal and availability rules** — measurement-window overlap, rental overlap with its turnaround buffer, explicit rental-asset choice gates, rental date ranges, post-measurement window placement, and expiry timing.
9. **Uniqueness and business constraints** — asset tags, fleet tags, schedule components, one certificate per savings case, monotonic run-hours, non-empty survey submission, segregation of duties, and the rental selector's empty pool.
10. **Fiscal gates** — the repair budget and contract-tier entitlements, evaluated last.

Where several checks within one tier guard the same endpoint, the workflow narratives in §3 pin their relative order (for example, the repair-authorization narrative in §3.4 fixes the order of its three state-tier gates, and the savings-case modeling narrative in §3.6 fixes which staleness error wins when both flags are set).

## 3. Business Logic & Workflows

### 3.1. Facility Onboarding and Lifecycle

A `DealerAdmin` brings a customer site onto the platform by creating a **Facility** with its display `name`, the blended `utility_rate_cents_per_kwh` that later prices guarantee payouts, the `operating_hours_per_year` that annualizes leak savings, and the `repair_budget_cents` that caps committed leak-repair quotes. A new facility starts in `ONBOARDING` status with `posture` `NORMAL` and both computed counters at zero: `repair_committed_cents`, the sum of `repair_quote_cents` over the facility's leak tags in `REPAIR_AUTHORIZED`, `REPAIRED`, or `VERIFIED_CLOSED`, and `rental_escrow_cents`, the sum of `deposit_cents` over the facility's rental reservations in `RESERVED` or `ON_RENT`. The facility list read supports filtering by `status` and by `posture`.

Activation moves the facility from `ONBOARDING` to `ACTIVE` and increments its `version`; most operational writes in this document require an `ACTIVE` facility and are otherwise rejected with `ERR_FACILITY_NOT_ACTIVE`. A `DealerAdmin` may suspend an `ACTIVE` facility to `SUSPENDED` and reinstate it back to `ACTIVE`; both transitions trigger a posture recompute and a refresh of certificate `settlement_blocked` for the facility, per §2.6.

Offboarding is the terminal exit, reachable from `ACTIVE` or `SUSPENDED`, and it is guarded by an open-obligations sweep evaluated in a fixed order: first contracts — no ServiceContract of the facility may be in `DRAFT`, `ACTIVE`, or `SUSPENDED`; then rentals — no RentalReservation may be in `RESERVED` or `ON_RENT`; then guarantees — no GuaranteeCertificate may be in `AWAITING_MEASUREMENT` or `SETTLED_PAYOUT_DUE`. Any open obligation rejects the offboard with `ERR_FACILITY_HAS_OPEN_OBLIGATIONS`. A clean offboard lands the facility in `OFFBOARDED`, its terminal state.

### 3.2. Compressor Registry, Run-Hours, and Dryer/Filter Maintenance

A `DealerAdmin` or `ServiceTech` registers a **Compressor** under a facility by supplying `facility_id`, the dealer `asset_tag`, the nameplate `rated_kw`, and the nameplate `rated_cfm` that later serves as the rental sizing reference; an initial cumulative `run_hours_total` may optionally be supplied and defaults to 0. The unit starts `IN_SERVICE`, and its registration triggers a facility posture recompute. Within a facility, an `asset_tag` must be unique among compressors that are not `DECOMMISSIONED`; a collision is rejected with `ERR_DUPLICATE_ASSET_TAG`. The compressor list read filters by `facility_id` and `status`.

Run-hours telemetry is monotonic. When a `ServiceTech` logs run-hours, the new `run_hours_total` must be at least the compressor's current value — a lower reading is a regression rejected with `ERR_RUN_HOURS_REGRESSION` (HTTP 422). Every logged reading ripples outward: schedule delinquency is recomputed, then facility posture, then certificate `settlement_blocked`, all within the same request.

Field condition drives the outage posture. Marking a compressor down — permitted only while its facility is not `OFFBOARDED` — moves it from `IN_SERVICE` to `DOWN`, and because even a single `DOWN` unit forces `OUTAGE_ACTIVE`, the posture recompute and certificate `settlement_blocked` refresh follow immediately. Returning the unit to service moves it from `DOWN` back to `IN_SERVICE`; the outage clears when the facility's last `DOWN` unit returns, again with the full recompute chain.

Decommissioning, reserved to `DealerAdmin` or `ContractManager`, moves a compressor from `IN_SERVICE` or `DOWN` to the terminal `DECOMMISSIONED` state and fires two cascades. First, every RetrofitProject of the facility in `PROPOSED`, `APPROVED`, or `INSTALLED` whose `sequence_compressor_ids` contains this unit is cancelled to `CANCELLED`. Second, every SavingsCase referencing one of those freshly cancelled projects while its `savings_status` is `DRAFT` or `MODELED` has its `retrofit_stale` flag set to true. The decommissioned unit also stops counting as `DOWN` and drops out of the facility's run-hour watermark, so the posture and `settlement_blocked` recompute that closes the request reflects its absence.

**Maintenance schedules** keep dryers and filters on interval against that watermark. A `DealerAdmin` or `ContractManager` creates a schedule with `facility_id`, a `component` of `DRYER` or `FILTER`, and an `interval_hours` greater than zero; only one `ACTIVE` schedule may exist per facility and component, and a duplicate is rejected with `ERR_DUPLICATE_SCHEDULE_COMPONENT`. At creation the schedule is `ACTIVE` with `anchor_run_hours` set to the facility's current run-hour watermark — the largest `run_hours_total` among its compressors that are not `DECOMMISSIONED`, or zero when it has none — and `next_due_run_hours` computed as the anchor plus the interval. A schedule's `is_delinquent` flag is true exactly when the schedule is `ACTIVE` and the facility watermark has reached or passed `next_due_run_hours`; reaching the due point precisely already counts as delinquent, because the comparison is inclusive. Schedule creation ends with a posture recompute.

Recording a service is how a `ServiceTech` resets the clock on a schedule. The call carries the `service_date` and the `run_hours_reading` observed at service time. Two checks guard it, evaluated in this order: the reading must be at least the schedule's current `anchor_run_hours` — a lower reading is rejected with `ERR_RUN_HOURS_REGRESSION` — and the reading must not exceed the facility watermark, because a technician cannot have serviced at a run-hour point no compressor has logged yet (`ERR_READING_EXCEEDS_LOGGED`, HTTP 422). A successful recording keeps the schedule `ACTIVE` while resetting `anchor_run_hours` to the reading, recomputing `next_due_run_hours`, and recomputing `is_delinquent` — which clears when the lifted anchor pushes the due point beyond the watermark. Posture and certificate `settlement_blocked` recompute as usual. A `ContractManager` retires a schedule from `ACTIVE` to the terminal `RETIRED` state; retired schedules never count as delinquent, and retirement triggers the same posture and settlement-flag refresh. The schedule list read filters by `facility_id`, `component`, and `status`.

### 3.3. Demand Profiles and Baseline Locking

Every savings claim begins with metered reality. An `EnergyEngineer` creates a **DemandProfile** for a facility with `facility_id`, an inclusive measurement window from `window_start_date` through `window_end_date`, the `measured_kwh` consumed over that window, and the average and peak airflow demand `measured_avg_cfm` and `measured_peak_cfm`, each at one decimal place. An end date earlier than the start date is an input failure rejected with `ERR_INVALID_REQUEST`. At creation the profile is `COLLECTING` and its `baseline_annual_kwh` is annualized: the measured kilowatt-hours are multiplied by 365 and divided by the window's length in days — counting both the first and the last calendar day of the window — with the result rounded half-up to a whole kilowatt-hour. The same annualization runs identically for baseline and post-retrofit profiles.

Windows for one facility may not collide. The inclusive window of a new profile must not intersect the window of any other profile of the same facility that is `COLLECTING` or `LOCKED`; sharing even a single calendar day already counts as an intersection, with no buffer day granted, and a collision is rejected with `ERR_MEASUREMENT_WINDOW_OVERLAP` (HTTP 409). Profiles that have been `SUPERSEDED` no longer block new windows. The profile list read filters by `facility_id`, `status`, and `superseded_by_id`.

Locking is the act that promotes a profile from draft telemetry to the facility's contractual baseline. An `EnergyEngineer` locks a `COLLECTING` profile; the gates are evaluated in order — the facility must be `ACTIVE` (`ERR_FACILITY_NOT_ACTIVE`), and then the optimistic-concurrency check of §2.7 applies, rejecting a stale `expected_facility_version` with `ERR_STALE_VERSION` (HTTP 412). A successful lock records the caller in `locked_by_user_id` — the segregation-of-duties reference that §3.6 later enforces at measurement close — and increments the facility's `version` by one. The lock also supersedes: the facility's previously `LOCKED` profile, if one exists, is transitioned to the terminal `SUPERSEDED` state with its `superseded_by_id` pointing at the newly locked profile, and every SavingsCase that pinned the superseded profile while its `savings_status` is `DRAFT` or `MODELED` has `baseline_stale` set to true. The move from `LOCKED` to `SUPERSEDED` is only ever this system cascade; no operator transitions a profile to `SUPERSEDED` directly.

### 3.4. Leak Surveys and the Repair Pipeline

A leak engagement starts in the field. An `EnergyEngineer` opens a **LeakSurvey** with `facility_id` and the `survey_date` of the field visit; the survey starts in `DRAFT`. While the survey is `DRAFT`, the engineer adds one **LeakTag** per discovered leak — a payload of `location_description`, the estimated `cfm_loss` (one decimal, always greater than zero), and the `repair_quote_cents` (zero or more) — and each tag starts `TAGGED` under its parent `survey_id`. Adding a tag to a survey that has left `DRAFT` is rejected with `ERR_INVALID_STATE_TRANSITION`. The survey list read filters by `facility_id` and `status`; the tag list read filters by `survey_id` and `status`.

Submission moves the survey from `DRAFT` to `SUBMITTED`. A survey must contain at least one tag to be submitted — an empty survey is rejected with `ERR_EMPTY_SURVEY` (HTTP 422). Submitting records the caller in `submitted_by_user_id` and cascades every contained tag from `TAGGED` to `QUOTED`.

Verification is a second pair of eyes: the `EnergyEngineer` who verifies a `SUBMITTED` survey must not be the one who submitted it, and a match between the caller and `submitted_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A successful verification lands the survey in its terminal `VERIFIED` state, records `verified_by_user_id`, and performs the survey's analytics in one pass. Each tag receives a `severity` — `LOW` when its `cfm_loss` is below 2.0, `MEDIUM` when the loss is at least 2.0 and at most 10.0, and `HIGH` above 10.0 — and a `priority_rank`: every tag in the survey, regardless of its status at verify time, is ordered by `cfm_loss` descending, with ties broken by `repair_quote_cents` ascending and any remaining ties by `created_at` ascending (never by identifier), and ranks are assigned as dense 1-based integers in that order. The survey itself gains `total_leak_cfm`, the sum of its tags' `cfm_loss` at one decimal, and `tag_count`, the number of tags it contains.

Repair authorization is where the customer's budget meets the ranked list. A `FacilityManager` authorizes a `QUOTED` tag, moving it to `REPAIR_AUTHORIZED`; the gates are evaluated in order — the tag's current state must permit the transition (`ERR_INVALID_STATE_TRANSITION`), the facility must be `ACTIVE` (`ERR_FACILITY_NOT_ACTIVE`), the parent survey must be `VERIFIED` (`ERR_SURVEY_NOT_VERIFIED`), and only then the fiscal gate: the facility's `repair_committed_cents` plus this tag's `repair_quote_cents` must not exceed the facility's `repair_budget_cents`, where landing exactly on the budget is allowed because the comparison is inclusive, and an overflow is rejected with `ERR_REPAIR_BUDGET_EXCEEDED` (HTTP 409). Authorization commits funds: the facility's `repair_committed_cents` grows by the quoted amount.

Execution and closure complete the loop. A `ServiceTech` marks an authorized tag `REPAIRED`, which records `repaired_by_user_id`. An `EnergyEngineer` then verifies the closure, moving the tag from `REPAIRED` to the terminal `VERIFIED_CLOSED` state and setting its `annual_kwh_savings`: the tag's `cfm_loss` is multiplied by 0.20 kilowatts per CFM and by the facility's `operating_hours_per_year`, and the product is rounded half-up to a whole kilowatt-hour. Closure is also a savings event — every SavingsCase of the same facility whose `savings_status` is `MODELED` recomputes its `deemed_annual_savings_kwh` immediately, per §3.6.

Not every leak is worth fixing. A `FacilityManager` may mark a tag `WONT_FIX` — a second terminal state — from either `QUOTED` or `REPAIR_AUTHORIZED`. Walking away from an authorized repair releases the commitment: the facility's `repair_committed_cents` is reduced by the tag's `repair_quote_cents`, a compensating action that keeps the committed total honest. From `QUOTED` the transition carries no fiscal effect, since nothing was committed yet.

### 3.5. Retrofit Projects and Compressor Sequencing

The engineering answer to a surveyed plant is a **RetrofitProject**: new pressure setpoints plus a deliberate compressor sequence. An `EnergyEngineer` proposes one with `facility_id`, the current `baseline_pressure_psi` setpoint, the post-retrofit `target_pressure_psi` — which must be strictly below the baseline, or the request fails schema validation with `ERR_INVALID_REQUEST` — an ordered `sequence_compressor_ids` array forming the sequencing plan, and the `project_cost_cents` that later caps the utility rebate. Every identifier in `sequence_compressor_ids` must resolve to a Compressor of the same facility; an unknown or foreign entry is rejected with `ERR_SEQUENCE_COMPRESSOR_INVALID` (HTTP 422). The project starts `PROPOSED` with `accepted_date` unset. The project list read filters by `facility_id` and `status`.

Approval belongs to the customer. A `FacilityManager` approves a `PROPOSED` project to `APPROVED`, and approval revalidates the sequence: every entry must still resolve to a compressor of the facility and must be `IN_SERVICE` at approval time, otherwise the approval is rejected with `ERR_SEQUENCE_COMPRESSOR_INVALID`. From there the dealer executes: a `ServiceTech` marks the project `INSTALLED` from `APPROVED`, then commissions it from `INSTALLED` to `COMMISSIONED`, and a `FacilityManager` accepts it from `COMMISSIONED` to the terminal `ACCEPTED` state, which stamps `accepted_date` with the current logical-clock date — the anchor against which §3.6's post-measurement window is later judged.

Cancellation is never a manual act. The only path to the second terminal state, `CANCELLED`, is the decommission cascade of §3.2: when a sequenced compressor is decommissioned, every project in `PROPOSED`, `APPROVED`, or `INSTALLED` that sequences it is cancelled, and each cancellation flags the referencing savings cases stale as described there. A project that has reached `COMMISSIONED` or `ACCEPTED` is beyond the cascade's reach.

### 3.6. Savings Cases, Measurement, and Utility Rebates

A **SavingsCase** is where engineering estimates become commercial instruments. It carries two independent state dimensions that evolve without touching each other: `savings_status` runs `DRAFT` to `MODELED` to `MEASUREMENT_OPEN` to the terminal `MEASURED`, while `rebate_status` runs `NONE` to `FILED` to a terminal `APPROVED` or `REJECTED`. Modeling a case, for instance, leaves its rebate dimension entirely alone.

An `EnergyEngineer` creates a case with `facility_id`, the `baseline_profile_id` it will be judged against, and the `retrofit_project_id` delivering the savings. Creation is gated, in order: the facility must be `ACTIVE` (`ERR_FACILITY_NOT_ACTIVE`); the baseline profile must be `LOCKED` (`ERR_PROFILE_NOT_LOCKED`); the retrofit project must be `APPROVED` or later — `APPROVED`, `INSTALLED`, `COMMISSIONED`, or `ACCEPTED` (`ERR_RETROFIT_NOT_APPROVED`); and both references must belong to the same facility as the case (`ERR_FACILITY_MISMATCH`). At creation the case pins `baseline_profile_version` to the profile's current `version`, so later supersession is detectable; `baseline_stale` and `retrofit_stale` start false; `savings_status` is `DRAFT` and `rebate_status` is `NONE`; `deemed_annual_savings_kwh` starts at 0 while `measured_annual_savings_kwh`, `post_profile_id`, `provisional_rebate_cents`, and `final_rebate_cents` remain unset. The case list read filters by `facility_id`, `baseline_profile_id`, `post_profile_id`, `retrofit_project_id`, `savings_status`, and `rebate_status`.

Modeling computes the **deemed** estimate. The transition from `DRAFT` to `MODELED` is gated by three checks in a pinned order: `baseline_stale` must be false — when both staleness flags happen to be set, `ERR_BASELINE_SUPERSEDED` is reported rather than `ERR_RETROFIT_STALE` — then `retrofit_stale` must be false (`ERR_RETROFIT_STALE`), and finally the referenced project must still be `APPROVED` or later (`ERR_RETROFIT_NOT_APPROVED`). The deemed figure combines two components. The leak component is the sum of the `annual_kwh_savings` of every `VERIFIED_CLOSED` leak tag belonging to a `VERIFIED` survey of the same facility — and because each tag's value was already rounded to a whole kilowatt-hour at closure (§3.4), the component is exactly that sum. Recomputing leak savings from raw CFM figures and rounding once after summing is a different, rejected formula: two leaks of 0.85 and 1.15 CFM at 5,933 annual operating hours yield 2,374 kWh under the pinned per-tag rounding but 2,373 kWh when raw products are summed and rounded once, and only the former is authoritative. The sequencing component credits the pressure reduction: the pressure drop is the project's `baseline_pressure_psi` minus its `target_pressure_psi`, capped at 20 psi when the raw drop is larger, and the component is the pinned baseline profile's `baseline_annual_kwh` multiplied by a percentage equal to 7 percent plus an additional 0.5 percent for each psi of capped pressure drop, the product rounded half-up to a whole kilowatt-hour. `deemed_annual_savings_kwh` is the sum of the two components, and the rounding order is pinned: round each leak first, then sum the leaks, then add the sequencing component. While a case sits in `MODELED`, any leak-tag verify-closure at the same facility (§3.4) recomputes this figure so the estimate tracks the completed repair work.

Staleness is recoverable through rebasing. When `baseline_stale` or `retrofit_stale` has been set — by a baseline supersede (§3.3) or a compressor decommission cascade (§3.2) — an `EnergyEngineer` rebases the case; calling rebase with neither flag set is rejected with `ERR_INVALID_STATE_TRANSITION`. Rebase requires a `LOCKED` profile to exist for the facility (`ERR_PROFILE_NOT_LOCKED`), and it may optionally carry a replacement `retrofit_project_id` in the body, which must be `APPROVED` or later (`ERR_RETROFIT_NOT_APPROVED`, the state-tier gate) and must belong to the same facility (`ERR_FACILITY_MISMATCH`, the referential-tier gate — evaluated in that tier order per §2.9). A rebase re-pins `baseline_profile_id` and `baseline_profile_version` to the facility's currently `LOCKED` profile and clears `baseline_stale`; when a replacement project is supplied, the case re-points to it and clears `retrofit_stale`. Either way, `savings_status` returns to `DRAFT` and `deemed_annual_savings_kwh` resets to 0 until the case is re-modeled.

Measurement replaces the estimate with metered proof. Opening measurement moves a `MODELED` case to `MEASUREMENT_OPEN` and requires the retrofit project to have reached `ACCEPTED` (`ERR_RETROFIT_NOT_ACCEPTED`). Closing it moves the case to the terminal `MEASURED` state; the call carries `post_profile_id`, the post-retrofit measurement profile, and its gates run in order — the post profile must be `LOCKED` (`ERR_PROFILE_NOT_LOCKED`), it must belong to the same facility (`ERR_FACILITY_MISMATCH`), its `window_start_date` must fall strictly after the project's `accepted_date` so the measurement reflects post-acceptance operation (`ERR_POST_WINDOW_BEFORE_ACCEPTANCE`), and segregation of duties forbids the caller from being the engineer recorded in the baseline profile's `locked_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`). On success the case stores `post_profile_id` and computes `measured_annual_savings_kwh`: the post profile is annualized with the same formula as any profile — its `measured_kwh` multiplied by 365 and divided by its inclusive window length in days, rounded half-up — and the measured savings is the pinned baseline's `baseline_annual_kwh` minus that annualized post figure. The result is signed: a negative value means the plant got worse, and the API reports it as-is.

The rebate dimension runs on its own track. Filing a rebate moves `rebate_status` from `NONE` to `FILED` and is available whenever `savings_status` is `MODELED` or `MEASURED`; from any other savings state the transition is undeclared and rejected with `ERR_INVALID_STATE_TRANSITION`. Filing computes `provisional_rebate_cents` from the rebate formula below over the **deemed** savings — always the deemed figure, even when the case is already `MEASURED` — and the provisional amount is never recomputed afterwards. Recording the utility's decision, done by a `DealerAdmin` or `ContractManager` supplying an `outcome` of `APPROVED` or `REJECTED`, moves `FILED` to the matching terminal state. Approval computes `final_rebate_cents` from the same formula but over the **measured** savings when the case is `MEASURED`, and over the deemed savings otherwise; rejection leaves `final_rebate_cents` unset.

The rebate formula itself is a two-tier energy incentive under two caps, always evaluated tiered amount first and caps after: 7 cents for each of the first 100,000 kilowatt-hours of savings, plus 3 cents for each kilowatt-hour beyond 100,000; then a cost cap of one half of the referenced project's `project_cost_cents`, rounded half-up to a whole cent; the payable rebate is the smallest of the tiered amount, the cost cap, and the program ceiling of 20,000,000 cents. Provisional and final rebates are the same formula applied at different stages to different savings inputs — deemed at filing, measured-if-available at approval — which is why a single case can legitimately carry two different rebate figures.

### 3.7. Service Contracts, Response SLAs, and Service Credits

A **ServiceContract** prices the dealer's ongoing obligation to a facility. A `ContractManager` drafts one with `facility_id`, a `tier` of `BASIC`, `STANDARD`, or `PREMIUM` — immutable after creation — the `start_date`, the coverage length `term_months` in whole months, and the gross `monthly_fee_cents`. Two fields derive at creation: `sla_base_hours` from the tier — 48 hours for `BASIC`, 24 for `STANDARD`, 8 for `PREMIUM` — and `end_date`, which falls the same day-of-month exactly `term_months` months after `start_date`. The contract starts in `DRAFT` with `sla_breach_count` at 0, `termination_penalty_waived` false, and all four credit counters — `credits_accrued_total_cents`, `credits_applied_total_cents`, `credits_expired_total_cents`, `credits_outstanding_cents` — at 0. The contract list read filters by `facility_id`, `tier`, and `status`.

Activation moves a contract from `DRAFT` to `ACTIVE` and is the second OCC-guarded write of §2.7: the facility must be `ACTIVE` (`ERR_FACILITY_NOT_ACTIVE`), evaluated first, and then `expected_facility_version` must match the facility's current `version` or the activation is rejected with `ERR_STALE_VERSION` (HTTP 412). Activation increments the facility's `version` by one and supersedes: the facility's currently `ACTIVE` contract, if one exists, is cascaded to `SUPERSEDED`, so at most one contract per facility is `ACTIVE` at a time.

From `ACTIVE`, a `ContractManager` may suspend the contract to `SUSPENDED` and reinstate it back to `ACTIVE`. Suspension also arrives uninvited: when a contract's `sla_breach_count` reaches 3, the system suspends it from `ACTIVE` to `SUSPENDED` automatically and sets `termination_penalty_waived` to true — the customer has earned the right to walk away. Termination, from `ACTIVE` or `SUSPENDED`, lands the contract in the terminal `TERMINATED` state and sets `termination_fee_cents`: zero when `termination_penalty_waived` is set, otherwise twice the `monthly_fee_cents`. Expiry is a separate terminal path from `ACTIVE` to `EXPIRED`, available only when the logical clock's date is strictly after `end_date` — the contract becomes expirable the day after its end date at the earliest, and an attempt on or before that date is rejected with `ERR_CONTRACT_NOT_EXPIRED`.

Service delivery runs on **ServiceTickets**. A `FacilityManager` opens a ticket with `facility_id`, the affected `compressor_id`, and a `severity` of `EMERGENCY`, `URGENT`, or `ROUTINE`. Creation gates run in order: the facility must be `ACTIVE` (`ERR_FACILITY_NOT_ACTIVE`); the facility must have a contract in `ACTIVE` — when there is no `ACTIVE` contract and none `SUSPENDED` either, creation is rejected with `ERR_NO_ACTIVE_CONTRACT`, and when the facility's latest non-terminal contract is `SUSPENDED`, it is rejected with `ERR_CONTRACT_SUSPENDED`; finally the compressor must belong to the calling facility (`ERR_FACILITY_MISMATCH`). At creation the server resolves `contract_id` to the facility's `ACTIVE` contract, stamps `reported_at` from the logical clock, captures `sla_tier_snapshot` from the contract's tier — a snapshot immune to whatever happens to the contract afterwards — and computes `sla_deadline`: `reported_at` plus the tier's base hours multiplied by the severity factor, where `EMERGENCY` multiplies by 1, `URGENT` by 2, and `ROUTINE` by 4. The ticket starts `OPEN`. The ticket list read filters by `facility_id`, `contract_id`, `compressor_id`, and `status`.

A `ServiceTech` dispatches an `OPEN` ticket to `DISPATCHED` and later records arrival, moving it from `DISPATCHED` to `ON_SITE`. Recording the response stamps `first_response_at` from the logical clock and computes `sla_met`: the SLA is met when the first response falls at or before `sla_deadline` — a response exactly at the deadline counts as met, because the comparison is inclusive. A missed SLA fires the breach cascade in the same request. A **ServiceCredit** is created with `source` `SLA_BREACH` — the only credit source in the system — in `ACCRUED` status, with `ticket_id` pointing at the breaching ticket, `contract_id` at the resolved contract, `accrued_at` from the logical clock, `expires_at` exactly ninety days after accrual, and `amount_cents` equal to 5 percent of the contract's gross `monthly_fee_cents`, rounded half-up to a whole cent. The base is deliberately the gross fee snapshot at accrual time, never the fee net of previously applied credits, so a credit's amount does not depend on the order in which earlier credits were applied. The cascade then updates the contract: `credits_accrued_total_cents` and `credits_outstanding_cents` each grow by the amount, and `sla_breach_count` — which counts the contract's ServiceCredit rows of any status — increments by one; when the count thereby reaches 3, the contract is automatically suspended and `termination_penalty_waived` set, as described above.

From `ON_SITE`, a `ServiceTech` resolves the ticket to the terminal `RESOLVED` state. A `FacilityManager` may cancel a ticket from `OPEN` or `DISPATCHED` to the terminal `CANCELLED` state.

Credits live out a short commercial life. A `ContractManager` applies an `ACCRUED` credit — moving it to the terminal `APPLIED` state — which decreases the contract's `credits_outstanding_cents` and increases `credits_applied_total_cents` by the amount. Alternatively, an `ACCRUED` credit expires to the terminal `EXPIRED` state once the logical clock has reached its `expires_at` instant — exactly at expiry counts, because the comparison is inclusive, and an earlier attempt is rejected with `ERR_CREDIT_NOT_EXPIRED` — moving the amount from `credits_outstanding_cents` to `credits_expired_total_cents`. Both paths preserve the contract's credit identity: `credits_accrued_total_cents` always equals `credits_applied_total_cents` plus `credits_expired_total_cents` plus `credits_outstanding_cents`, and the accrued total is immutable once added — it is the all-time sum of every credit amount ever accrued. The credit list read filters by `contract_id`, `ticket_id`, and `status`.

### 3.8. Rental Fleet Operations and Outage Substitution

When a compressor goes down, the dealer's rental fleet bridges the gap. A `DealerAdmin` registers each **RentalAsset** with a globally unique `fleet_tag` — a duplicate is rejected with `ERR_DUPLICATE_FLEET_TAG` — its `rated_cfm` capacity, the per-calendar-day `daily_rate_cents`, and the escrow `deposit_cents` held while the unit is out. An asset starts `AVAILABLE` with `next_available_date` unset. The fleet list read filters by `status` and by `min_rated_cfm`, a minimum-capacity threshold for sizing searches.

Fleet upkeep is a manual toggle: a `ServiceTech` or `DealerAdmin` sets `in_maintenance` true to move an `AVAILABLE` asset to `IN_MAINTENANCE` — blocked with `ERR_RENTAL_ASSET_UNAVAILABLE` while any reservation on the asset is `RESERVED` or `ON_RENT` — and sets it false to return the asset to `AVAILABLE`. The `ON_RENT` state is never set by hand: it is driven by reservation delivery and return, as below.

A **RentalReservation** substitutes capacity for a down unit. A `FacilityManager` creates one with `facility_id`, the `down_compressor_id` being substituted, the `start_date` and planned `end_date`, and an optional `rental_asset_id` naming a specific unit. The gates run in the priority order of §2.9: the facility must be `ACTIVE` (`ERR_FACILITY_NOT_ACTIVE`); the facility must have an `ACTIVE` contract — `ERR_NO_ACTIVE_CONTRACT` when there is none and nothing suspended, `ERR_CONTRACT_SUSPENDED` when the latest non-terminal contract is `SUSPENDED`; the referenced compressor's status must be `DOWN` (`ERR_COMPRESSOR_NOT_DOWN`); the down compressor must belong to the calling facility (`ERR_FACILITY_MISMATCH`); then the temporal tier — the asset must be free of buffered overlap and, when explicitly named, must itself be `AVAILABLE` with `rated_cfm` at least the down unit's `rated_cfm` (`ERR_RENTAL_ASSET_UNAVAILABLE` on either count) — and `end_date` must not precede `start_date` (`ERR_RENTAL_DATE_RANGE_INVALID`, HTTP 422); then, when no asset was named and the selector finds nothing, `ERR_NO_RENTAL_ASSET_AVAILABLE`; and finally the fiscal tier: the facility's `ACTIVE` contract must be `STANDARD` or `PREMIUM` — `BASIC` entitles the customer to no rental — or the reservation is rejected with `ERR_CONTRACT_TIER_INELIGIBLE`.

The overlap rule carries a turnaround buffer. For a candidate asset, each existing reservation in `RESERVED`, `ON_RENT`, `RETURNED`, or `INVOICED` occupies an interval from its `start_date` through one day after its effective end — the effective end being its `actual_return_date` once the reservation is `RETURNED` or `INVOICED`, otherwise its planned `end_date` — with both endpoints inclusive. A new reservation whose own inclusive start-to-end interval intersects any occupied interval is rejected with `ERR_RENTAL_ASSET_UNAVAILABLE`; because the buffer day belongs to the earlier reservation, a new start exactly two calendar days after an occupied end is the earliest legal adjacency.

When the request omits `rental_asset_id`, the server selects on the customer's behalf. Eligible assets are `AVAILABLE`, have `rated_cfm` at least the down compressor's `rated_cfm`, and carry no buffered overlap as just defined. The selector ranks survivors by `rated_cfm` ascending — the smallest sufficient unit wins — with ties broken by `created_at` ascending, and an empty eligible pool is rejected with `ERR_NO_RENTAL_ASSET_AVAILABLE`.

A created reservation starts `RESERVED`: `rental_asset_id` holds the explicit or selected asset, `deposit_cents` snapshots the asset's deposit at that moment, `planned_days` counts every calendar day from `start_date` through `end_date` inclusive, and `quoted_cents` is the quote variant of the rental bill — `planned_days` times the asset's `daily_rate_cents`, with no minimum-days floor and no long-term discount. The reservation also moves money: the facility's `rental_escrow_cents` grows by the snapshotted deposit.

Delivery, by a `ServiceTech`, moves the reservation from `RESERVED` to `ON_RENT` and cascades the asset to `ON_RENT`. Return, also by a `ServiceTech`, moves it from `ON_RENT` to `RETURNED`; the body carries `actual_return_date`, which must not precede the `start_date` (`ERR_RENTAL_DATE_RANGE_INVALID`). Return computes the actual variant of the bill into `actual_bill_cents`: the actual rental days run from `start_date` through `actual_return_date` inclusive; billable days are the actual days raised to a minimum of 3 when the rental ran shorter; the first 27 billable days are charged at the full daily rate and any billable days beyond the twenty-seventh at 85 percent of it; and the resulting amount is rounded half-up exactly once, at the end, to a whole cent. Return also frees the asset to `AVAILABLE` with `next_available_date` set to the day after the return — the turnaround buffer the overlap rule enforces — and releases the deposit by reducing the facility's `rental_escrow_cents` accordingly. Quote and actual are two legitimate variants of one reservation: the quote is computed over planned days at creation, the actual over real duration with its floor and discount at return, and the two totals may differ.

Two closing paths remain. A `FacilityManager` cancels a `RESERVED` reservation to the terminal `CANCELLED` state, which releases the deposit — the facility's `rental_escrow_cents` decreases by the snapshotted amount, so a create-then-cancel pair nets zero escrow drift. A `ContractManager` invoices a `RETURNED` reservation to the terminal `INVOICED` state, locking `final_bill_cents` as a frozen copy of `actual_bill_cents`. The reservation list read filters by `facility_id`, `rental_asset_id`, `down_compressor_id`, and `status`.

### 3.9. Guarantee Certificates, Settlement, and Measurement Disputes

The premium commercial product is the **GuaranteeCertificate**: a payout promise over a savings case. A `ContractManager` creates one with `facility_id`, the covering `contract_id`, the `savings_case_id` being guaranteed, and `guaranteed_pct`, the fraction of deemed savings underwritten — for example 0.90. The contract must belong to the same facility, be `ACTIVE`, and carry tier `PREMIUM`; the savings case must belong to the same facility with `savings_status` `MODELED` or `MEASURED`; and at most one certificate may exist per savings case. The gates evaluate in order: contract presence (`ERR_NO_ACTIVE_CONTRACT`), cross-facility referential integrity (`ERR_FACILITY_MISMATCH`), the one-certificate-per-case uniqueness (`ERR_CERTIFICATE_EXISTS`), and the tier entitlement (`ERR_CONTRACT_TIER_INELIGIBLE`).

Creation snapshots the guarantee basis and never looks back. `guaranteed_kwh` is the savings case's `deemed_annual_savings_kwh` at creation time multiplied by `guaranteed_pct`, rounded half-up to a whole kilowatt-hour; it is a snapshot that is never recomputed, even when the case's deemed figure later changes. `deadband_kwh`, the measurement-uncertainty allowance, is 2 percent of `guaranteed_kwh`, rounded half-up to a whole kilowatt-hour. The certificate starts with `settlement_status` `AWAITING_MEASUREMENT` and `dispute_status` `NONE` — two independent dimensions, the first running toward the terminal `PAID`, the second toward terminal `RESOLVED_UPHELD` or `RESOLVED_OVERRULED` — and its `settlement_blocked` flag is computed from the facility's current posture, then refreshed by every posture recompute per §2.6. The certificate list read filters by `facility_id`, `contract_id`, `savings_case_id`, and `settlement_status`.

Settlement is the moment of truth, performed by a `ContractManager`. Its gates run in order: the linked savings case must be `MEASURED` (`ERR_MEASUREMENT_INCOMPLETE`); the facility's posture must be `NORMAL` (`ERR_POSTURE_NOT_NORMAL`); and no dispute may be open. Settling pulls `measured_kwh_at_settlement` from the case's `measured_annual_savings_kwh`, then computes `shortfall_kwh` as the `guaranteed_kwh` minus the measured value minus the `deadband_kwh` — the deadband is subtracted before clamping — floored at zero, and `payout_cents` as the shortfall multiplied by the facility's `utility_rate_cents_per_kwh`, rounded half-up to a whole cent, capped at twelve times the contract's `monthly_fee_cents`. The rounding order is pinned: guarantee first, then deadband, then shortfall, then payout. A zero shortfall settles to `SETTLED_NO_SHORTFALL` with `payout_cents` zero; a positive shortfall settles to `SETTLED_PAYOUT_DUE`.

Payment moves a certificate from `SETTLED_PAYOUT_DUE` to the terminal `PAID`, but a dispute freezes it: while `dispute_status` is `OPEN`, paying is rejected with `ERR_DISPUTE_OPEN_PAYOUT_FROZEN`; with `dispute_status` `NONE`, `RESOLVED_UPHELD`, or `RESOLVED_OVERRULED`, payment proceeds.

The dispute track belongs to the customer. A `FacilityManager` opens a dispute — supplying a `reason` that is stored in `dispute_reason` — on a certificate that is settled but unpaid, that is, in `SETTLED_NO_SHORTFALL` or `SETTLED_PAYOUT_DUE`; a `PAID` certificate is beyond dispute. Opening moves `dispute_status` from `NONE` to `OPEN` and freezes the payout. A `ContractManager` then resolves the dispute by supplying an `outcome`. An `UPHELD` outcome requires `corrected_measured_kwh` in the request body — its absence is a schema failure, `ERR_INVALID_REQUEST` — and it re-runs settlement with the corrected figure: `measured_kwh_at_settlement` becomes the corrected value, `shortfall_kwh` and `payout_cents` are recomputed by the same pinned formula, and `settlement_status` is re-derived, landing on `SETTLED_NO_SHORTFALL` when the recomputed shortfall is zero and `SETTLED_PAYOUT_DUE` otherwise; the re-derivation cannot collide with `PAID`, because payment is impossible while a dispute is open. An `OVERRULED` outcome leaves every settlement figure unchanged and simply releases the payout for a subsequent pay call. Resolution lands the dispute dimension in its terminal `RESOLVED_UPHELD` or `RESOLVED_OVERRULED` state.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including every state-transition action — return `200 OK`; list and single-resource reads return `200 OK`. Request payloads, computed fields, and side effects are specified by the workflow narratives in §3; this table is only the HTTP contract and role assignment.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | DealerAdmin |
| POST | `/facilities` | Create a Facility in ONBOARDING with posture NORMAL | DealerAdmin |
| GET | `/facilities` | List facilities with optional filters and pagination | All roles |
| GET | `/facilities/{facilityId}` | Get a Facility | All roles |
| POST | `/facilities/{facilityId}/activate` | ONBOARDING -> ACTIVE | DealerAdmin |
| POST | `/facilities/{facilityId}/suspend` | ACTIVE -> SUSPENDED | DealerAdmin |
| POST | `/facilities/{facilityId}/reinstate` | SUSPENDED -> ACTIVE | DealerAdmin |
| POST | `/facilities/{facilityId}/offboard` | ACTIVE or SUSPENDED -> OFFBOARDED; blocked by open obligations | DealerAdmin |
| POST | `/compressors` | Register a Compressor (IN_SERVICE) | DealerAdmin, ServiceTech |
| GET | `/compressors` | List compressors | All roles |
| GET | `/compressors/{compressorId}` | Get a Compressor | All roles |
| POST | `/compressors/{compressorId}/log-run-hours` | Set cumulative run-hours (monotonic); recomputes delinquency and posture | ServiceTech |
| POST | `/compressors/{compressorId}/mark-down` | IN_SERVICE -> DOWN (opens outage posture) | ServiceTech |
| POST | `/compressors/{compressorId}/return-to-service` | DOWN -> IN_SERVICE | ServiceTech |
| POST | `/compressors/{compressorId}/decommission` | IN_SERVICE or DOWN -> DECOMMISSIONED; cancels referencing retrofit projects; flags savings cases stale | DealerAdmin, ContractManager |
| POST | `/demand-profiles` | Create a DemandProfile (COLLECTING); per-facility window overlap check | EnergyEngineer |
| GET | `/demand-profiles` | List demand profiles | All roles |
| GET | `/demand-profiles/{demandProfileId}` | Get a DemandProfile | All roles |
| POST | `/demand-profiles/{demandProfileId}/lock` | COLLECTING -> LOCKED with OCC; supersedes the facility's prior LOCKED profile | EnergyEngineer |
| POST | `/leak-surveys` | Create a LeakSurvey (DRAFT) | EnergyEngineer |
| GET | `/leak-surveys` | List leak surveys | All roles |
| GET | `/leak-surveys/{leakSurveyId}` | Get a LeakSurvey | All roles |
| POST | `/leak-surveys/{leakSurveyId}/leak-tags` | Add a LeakTag to a DRAFT survey | EnergyEngineer |
| GET | `/leak-tags` | List leak tags | All roles |
| GET | `/leak-tags/{leakTagId}` | Get a LeakTag | All roles |
| POST | `/leak-surveys/{leakSurveyId}/submit` | DRAFT -> SUBMITTED; requires at least one tag; tags TAGGED -> QUOTED | EnergyEngineer |
| POST | `/leak-surveys/{leakSurveyId}/verify` | SUBMITTED -> VERIFIED; verifier must differ from submitter; computes severity, ranks, and totals | EnergyEngineer |
| POST | `/leak-tags/{leakTagId}/authorize-repair` | QUOTED -> REPAIR_AUTHORIZED; gates: survey VERIFIED, facility ACTIVE, repair budget | FacilityManager |
| POST | `/leak-tags/{leakTagId}/mark-repaired` | REPAIR_AUTHORIZED -> REPAIRED | ServiceTech |
| POST | `/leak-tags/{leakTagId}/verify-closure` | REPAIRED -> VERIFIED_CLOSED; computes annual savings; recomputes deemed savings on MODELED cases | EnergyEngineer |
| POST | `/leak-tags/{leakTagId}/mark-wont-fix` | QUOTED or REPAIR_AUTHORIZED -> WONT_FIX; releases budget commitment when authorized | FacilityManager |
| POST | `/maintenance-schedules` | Create a dryer/filter MaintenanceSchedule (ACTIVE); anchor = facility max compressor run-hours | DealerAdmin, ContractManager |
| GET | `/maintenance-schedules` | List maintenance schedules | All roles |
| GET | `/maintenance-schedules/{maintenanceScheduleId}` | Get a MaintenanceSchedule | All roles |
| POST | `/maintenance-schedules/{maintenanceScheduleId}/record-service` | Record dryer/filter service; resets anchor and recomputes delinquency | ServiceTech |
| POST | `/maintenance-schedules/{maintenanceScheduleId}/retire` | ACTIVE -> RETIRED | ContractManager |
| POST | `/retrofit-projects` | Create a RetrofitProject (PROPOSED); sequence compressors validated against facility | EnergyEngineer |
| GET | `/retrofit-projects` | List retrofit projects | All roles |
| GET | `/retrofit-projects/{retrofitProjectId}` | Get a RetrofitProject | All roles |
| POST | `/retrofit-projects/{retrofitProjectId}/approve` | PROPOSED -> APPROVED; revalidates sequenced compressors are IN_SERVICE | FacilityManager |
| POST | `/retrofit-projects/{retrofitProjectId}/mark-installed` | APPROVED -> INSTALLED | ServiceTech |
| POST | `/retrofit-projects/{retrofitProjectId}/commission` | INSTALLED -> COMMISSIONED | ServiceTech |
| POST | `/retrofit-projects/{retrofitProjectId}/accept` | COMMISSIONED -> ACCEPTED; stamps accepted_date from the logical clock | FacilityManager |
| POST | `/savings-cases` | Create a SavingsCase (savings DRAFT / rebate NONE); pins baseline profile id and version | EnergyEngineer |
| GET | `/savings-cases` | List savings cases | All roles |
| GET | `/savings-cases/{savingsCaseId}` | Get a SavingsCase | All roles |
| POST | `/savings-cases/{savingsCaseId}/model` | savings DRAFT -> MODELED; computes deemed annual savings | EnergyEngineer |
| POST | `/savings-cases/{savingsCaseId}/rebase` | Clear staleness: re-pin the current LOCKED baseline (and optionally re-point the retrofit project); resets savings to DRAFT | EnergyEngineer |
| POST | `/savings-cases/{savingsCaseId}/open-measurement` | savings MODELED -> MEASUREMENT_OPEN; requires retrofit ACCEPTED | EnergyEngineer |
| POST | `/savings-cases/{savingsCaseId}/close-measurement` | savings MEASUREMENT_OPEN -> MEASURED; computes measured savings; segregation of duties vs baseline locker | EnergyEngineer |
| POST | `/savings-cases/{savingsCaseId}/file-rebate` | rebate NONE -> FILED; provisional rebate always computed from deemed savings | EnergyEngineer |
| POST | `/savings-cases/{savingsCaseId}/record-rebate-decision` | rebate FILED -> APPROVED or REJECTED; APPROVED computes the final rebate from measured (if MEASURED) else deemed | DealerAdmin, ContractManager |
| POST | `/service-contracts` | Create a ServiceContract (DRAFT); SLA base hours and end date computed | ContractManager |
| GET | `/service-contracts` | List service contracts | All roles |
| GET | `/service-contracts/{serviceContractId}` | Get a ServiceContract | All roles |
| POST | `/service-contracts/{serviceContractId}/activate` | DRAFT -> ACTIVE with OCC on the Facility version; supersedes the facility's currently ACTIVE contract | ContractManager |
| POST | `/service-contracts/{serviceContractId}/suspend` | ACTIVE -> SUSPENDED | ContractManager |
| POST | `/service-contracts/{serviceContractId}/reinstate` | SUSPENDED -> ACTIVE | ContractManager |
| POST | `/service-contracts/{serviceContractId}/terminate` | ACTIVE or SUSPENDED -> TERMINATED; fee waived when the termination penalty is waived | ContractManager |
| POST | `/service-contracts/{serviceContractId}/expire` | ACTIVE -> EXPIRED; only when the logical clock date is past the end date | ContractManager |
| POST | `/service-tickets` | Open a ServiceTicket (OPEN); resolves the ACTIVE contract, stamps reported_at and sla_deadline from the logical clock | FacilityManager |
| GET | `/service-tickets` | List service tickets | All roles |
| GET | `/service-tickets/{serviceTicketId}` | Get a ServiceTicket | All roles |
| POST | `/service-tickets/{serviceTicketId}/dispatch` | OPEN -> DISPATCHED | ServiceTech |
| POST | `/service-tickets/{serviceTicketId}/record-response` | DISPATCHED -> ON_SITE; stamps first_response_at, computes sla_met, fires the breach cascade | ServiceTech |
| POST | `/service-tickets/{serviceTicketId}/resolve` | ON_SITE -> RESOLVED | ServiceTech |
| POST | `/service-tickets/{serviceTicketId}/cancel` | OPEN or DISPATCHED -> CANCELLED | FacilityManager |
| POST | `/rental-assets` | Add a RentalAsset to the dealer fleet (AVAILABLE) | DealerAdmin |
| GET | `/rental-assets` | List the rental fleet | All roles |
| GET | `/rental-assets/{rentalAssetId}` | Get a RentalAsset | All roles |
| POST | `/rental-assets/{rentalAssetId}/set-maintenance` | AVAILABLE <-> IN_MAINTENANCE; entering maintenance blocked by active reservations | ServiceTech, DealerAdmin |
| POST | `/rental-reservations` | Reserve a rental compressor for a DOWN unit; auto-selects the smallest sufficient available asset when no asset is named | FacilityManager |
| GET | `/rental-reservations` | List rental reservations | All roles |
| GET | `/rental-reservations/{rentalReservationId}` | Get a RentalReservation | All roles |
| POST | `/rental-reservations/{rentalReservationId}/deliver` | RESERVED -> ON_RENT; the asset goes ON_RENT | ServiceTech |
| POST | `/rental-reservations/{rentalReservationId}/return` | ON_RENT -> RETURNED; computes the actual bill; frees the asset after the turnaround buffer; releases the deposit | ServiceTech |
| POST | `/rental-reservations/{rentalReservationId}/cancel` | RESERVED -> CANCELLED; releases the deposit | FacilityManager |
| POST | `/rental-reservations/{rentalReservationId}/invoice` | RETURNED -> INVOICED; locks final_bill_cents | ContractManager |
| POST | `/guarantee-certificates` | Create a GuaranteeCertificate (AWAITING_MEASUREMENT / dispute NONE); snapshots guaranteed kWh and deadband from the case's deemed savings | ContractManager |
| GET | `/guarantee-certificates` | List guarantee certificates | All roles |
| GET | `/guarantee-certificates/{guaranteeCertificateId}` | Get a GuaranteeCertificate | All roles |
| POST | `/guarantee-certificates/{guaranteeCertificateId}/settle` | AWAITING_MEASUREMENT -> SETTLED_NO_SHORTFALL or SETTLED_PAYOUT_DUE; gates: case MEASURED, posture NORMAL, dispute NONE | ContractManager |
| POST | `/guarantee-certificates/{guaranteeCertificateId}/pay` | SETTLED_PAYOUT_DUE -> PAID; blocked while a dispute is OPEN | ContractManager |
| POST | `/guarantee-certificates/{guaranteeCertificateId}/dispute` | Open a measurement dispute (dispute NONE -> OPEN) on a settled-but-unpaid certificate; freezes payout | FacilityManager |
| POST | `/guarantee-certificates/{guaranteeCertificateId}/resolve-dispute` | Resolve a dispute: UPHELD recomputes shortfall and payout with the corrected measurement and re-derives settlement; OVERRULED releases the payout unchanged | ContractManager |
| GET | `/service-credits` | List service credits | All roles |
| GET | `/service-credits/{serviceCreditId}` | Get a ServiceCredit | All roles |
| POST | `/service-credits/{serviceCreditId}/apply` | ACCRUED -> APPLIED; contract outstanding decreases, applied increases | ContractManager |
| POST | `/service-credits/{serviceCreditId}/expire` | ACCRUED -> EXPIRED; requires the logical clock to have reached expires_at | ContractManager |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this catalogue fixes only the identifier and the HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_FACILITY_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_FACILITY_NOT_ACTIVE` | 409 Conflict |
| `ERR_FACILITY_HAS_OPEN_OBLIGATIONS` | 409 Conflict |
| `ERR_NO_ACTIVE_CONTRACT` | 409 Conflict |
| `ERR_CONTRACT_SUSPENDED` | 409 Conflict |
| `ERR_CONTRACT_NOT_EXPIRED` | 409 Conflict |
| `ERR_CONTRACT_TIER_INELIGIBLE` | 409 Conflict |
| `ERR_COMPRESSOR_NOT_DOWN` | 409 Conflict |
| `ERR_DUPLICATE_ASSET_TAG` | 409 Conflict |
| `ERR_DUPLICATE_SCHEDULE_COMPONENT` | 409 Conflict |
| `ERR_MEASUREMENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PROFILE_NOT_LOCKED` | 409 Conflict |
| `ERR_BASELINE_SUPERSEDED` | 409 Conflict |
| `ERR_RETROFIT_STALE` | 409 Conflict |
| `ERR_RETROFIT_NOT_APPROVED` | 409 Conflict |
| `ERR_RETROFIT_NOT_ACCEPTED` | 409 Conflict |
| `ERR_POST_WINDOW_BEFORE_ACCEPTANCE` | 409 Conflict |
| `ERR_FACILITY_MISMATCH` | 409 Conflict |
| `ERR_SURVEY_NOT_VERIFIED` | 409 Conflict |
| `ERR_REPAIR_BUDGET_EXCEEDED` | 409 Conflict |
| `ERR_NO_RENTAL_ASSET_AVAILABLE` | 409 Conflict |
| `ERR_RENTAL_ASSET_UNAVAILABLE` | 409 Conflict |
| `ERR_DUPLICATE_FLEET_TAG` | 409 Conflict |
| `ERR_MEASUREMENT_INCOMPLETE` | 409 Conflict |
| `ERR_POSTURE_NOT_NORMAL` | 409 Conflict |
| `ERR_DISPUTE_OPEN_PAYOUT_FROZEN` | 409 Conflict |
| `ERR_CERTIFICATE_EXISTS` | 409 Conflict |
| `ERR_CREDIT_NOT_EXPIRED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_RUN_HOURS_REGRESSION` | 422 Unprocessable Entity |
| `ERR_READING_EXCEEDS_LOGGED` | 422 Unprocessable Entity |
| `ERR_SEQUENCE_COMPRESSOR_INVALID` | 422 Unprocessable Entity |
| `ERR_EMPTY_SURVEY` | 422 Unprocessable Entity |
| `ERR_RENTAL_DATE_RANGE_INVALID` | 422 Unprocessable Entity |
