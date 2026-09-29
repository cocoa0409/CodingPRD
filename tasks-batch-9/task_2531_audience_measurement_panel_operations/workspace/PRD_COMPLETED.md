# Audience Measurement Panel Operations API — Product Requirements Document

## 1. Introduction

Syndicated audience measurement rests on a paradox: the numbers a broadcaster, an agency and an advertiser all trade against are produced from a panel of a few thousand consenting households, and the credibility of those numbers depends far more on the discipline of the operational record than on the size of the sample. This document specifies the API for an audience measurement panel operations platform — the system of record for recruiting households against demographic and geographic quota targets, deploying and monitoring metering hardware, editing raw tuning records under a published rule set, weighting the surviving records up to a population universe, and delivering the resulting projections to subscribing clients under contractual service levels.

Three pressures shape every requirement that follows. The first is **quota discipline**: a panel is only projectable if its in-tab composition can be defended cell by cell, so the platform tracks recruitment against per-cell targets, escalates cooperation incentives when a cell falls behind, and refuses intake into cells and markets that have no room or no clearance. The second is **methodological traceability**: every published number must name the population universe vintage and the editing rule set that produced it, and if either is retired the affected work must visibly stall rather than silently drift. The third is **accountable disclosure**: accreditation bodies audit the methodology, methodology changes must be disclosed to clients before they take effect, and limitations recorded by an auditor must travel with the data forever after.

Operationally the platform serves seven distinct professional communities — panel operations, field technicians, methodology statisticians, client service, the subscribers themselves, accreditation auditors and methodology governance — whose duties are deliberately kept separate. The operator who opens a processing run may not publish it; the auditor who opens an accreditation audit may not finalize it; the director who drafts a methodology change may not activate it. Because almost every rule in this domain is a deadline, a tenure, a window or a lateness calculation, the platform reads a single server-held **logical clock** rather than wall-clock time, and that clock is advanced explicitly.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts that hold across the whole API: authentication, the response envelope, pagination, the logical clock, common record properties, validation ordering, concurrency, numeric precision, cascade discipline, segregation of duties, and the accreditation gates that sit above everything else. One precondition frames all of them: the platform starts empty. No market, quota cell, universe vintage, rule set, household, meter, client or governance row is seeded, preloaded or hardcoded at startup, so every row a caller can read is one some caller created through an endpoint declared in §4, and the logical clock's startup value in §2.4 is the only piece of state that exists before the first request.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the capacity in which that principal is acting. If `X-User-ID` is missing, empty or entirely whitespace, or if `X-User-Role` is absent or does not name one of the seven roles below exactly — the match is case-sensitive and admits no surrounding whitespace — the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not authorised for the operation being attempted, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The seven recognised roles are `PanelOperationsManager`, `FieldTechnician`, `MethodologyStatistician`, `ClientServiceRep`, `ClientUser`, `AccreditationAuditor` and `GovernanceDirector`.

- A `PanelOperationsManager` owns the market surface: registering markets and quota cells, moving the incentive budget, recruiting and retiring households, and running the cooperation-incentive ledger.
- A `FieldTechnician` owns the field surface: shipping, installing, fault-reporting, repairing and removing meters, and performing household enumerations.
- A `MethodologyStatistician` owns the measurement pipeline: universe vintages, editing rule sets, interval ingest, and the open/edit/weight/publish run cycle.
- A `ClientServiceRep` owns the commercial surface: client records, tier assignment, suspension and reinstatement, the delivery schedule, and the analyst side of deliverables.
- A `ClientUser` is the subscriber acting for itself, and may only acknowledge notifications and request revisions on its own deliverables.
- An `AccreditationAuditor` is the independent auditor of methodology, opening and finalizing accreditation audits.
- A `GovernanceDirector` owns methodology change management: drafting a change, running its impact analysis, notifying clients, requesting revisions and activating the change.

**Identity semantics.** When `X-User-Role` is `PanelOperationsManager`, `FieldTechnician`, `MethodologyStatistician`, `ClientServiceRep`, `AccreditationAuditor` or `GovernanceDirector`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server records it where a rule requires an operator identity — as `opened_by_user_id` and `published_by_user_id` on a processing run, as `opened_by_user_id` and `finalized_by_user_id` on an accreditation audit, and as `created_by_user_id` on a methodology change — but it never compares it to any entity's `id`. When `X-User-Role` is `ClientUser`, by contrast, `X-User-ID` is the `id` of the acting `Client` row: ownership checks on any resource that references a client compare that resource's client foreign key to `X-User-ID`. Concretely, a `ClientUser` requesting a revision on a deliverable is refused with `ERR_UNAUTHORIZED` unless `X-User-ID` equals that deliverable's `client_id`, and a `ClientUser` acknowledging a notification is refused with `ERR_UNAUTHORIZED` unless `X-User-ID` equals that notification's `client_id`. This client-scoping check is evaluated immediately after the role check and before any existence or state check on the row's own business fields.

**Read access and confidentiality.** All seven roles may advance the logical clock, and all seven roles may read markets, quota cells, universe vintages, editing rule sets, households, meters, processing runs, clients, deliverables, notifications and accreditation audits. Two read surfaces are confidential because they expose respondent-level records: tuning intervals and household weights may only be read by a `PanelOperationsManager`, a `MethodologyStatistician` or an `AccreditationAuditor`. Any other role attempting those reads receives `ERR_UNAUTHORIZED`.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`, formed as the literal `req_` followed by exactly twenty characters drawn from the uppercase letters and the digits.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from real wall-clock time rather than from the logical clock of §2.4 — the envelope stamp is diagnostic metadata, not one of the business timestamps that clock governs.
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

### 2.3. Pagination, Ordering and Collection Filters

Every collection read is paginated by the same two query parameters. `limit` caps the number of rows returned; when omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` is the number of rows to skip before the page begins and defaults to 0. Both are reflected back in the envelope's `meta` object, alongside `total_count` (the number of rows the filter matched before pagination) and `has_more` (true when rows remain beyond this page). A `limit` that is not an integer, or one below 1 or above 100, and an `offset` that is not an integer or is negative, are each refused with `ERR_INVALID_REQUEST` (HTTP 422) rather than clamped to the permitted band; surrounding whitespace on either value is tolerated.

Unless a collection states otherwise below, list results are ordered by `created_at` ascending, and because `created_at` is read from the logical clock a shared timestamp is routine rather than exceptional: rows carrying the same `created_at` are ordered by ascending insertion sequence, and that same insertion-sequence tie-break settles any tie the three overrides below leave open. Three collections override the default, and the override is part of the contract:

- Markets are ordered newest first — by `created_at` descending, and ties broken by `market_code` ascending.
- Tuning intervals are ordered by `start_iso` ascending, ties broken by `created_at` ascending.
- Processing runs are ordered by `window_start_iso` ascending, ties broken by `created_at` ascending.

Each collection also accepts optional equality filters, all of them independent and combinable. A string-valued filter matches by exact equality against the stored value, with no case folding and no trimming. The boolean-valued filters — `incentive_boost_active`, `ascribed` and `capped` — accept `true`, `false`, `1` or `0` in any letter case and refuse anything else with `ERR_INVALID_REQUEST`. A query parameter a collection does not declare is ignored rather than rejected, and a declared filter supplied more than once is read from its first occurrence. Filter values are validated before `limit` and `offset` are, so a request that gets both wrong is answered with the filter failure.

- Markets: `recruitment_posture`, `accreditation_status`.
- Quota cells: `market_id`, `quota_status`, `incentive_boost_active`.
- Universe estimates: `market_id`, `status`.
- Editing rule sets: `status`.
- Households: `market_id`, `quota_cell_id`, `status`, `enumeration_verdict`.
- Meters: `household_id`, `install_status`, `health_status`, `meter_type`.
- Tuning intervals: `meter_id`, `household_id`, `processing_run_id`, `state`, `source_methodology`, `ascribed`.
- Processing runs: `market_id`, `universe_estimate_id`, `edit_rule_set_id`, `state`, `weight_variant`.
- Household weights: `processing_run_id`, `household_id`, `capped`, `weight_variant`.
- Clients: `tier`, `status`.
- Client deliverables: `client_id`, `processing_run_id`, `kind`, `state`, `hold_reason`.
- Client notifications: `methodology_change_id`, `client_id`, `state`, `impact_tier`.
- Accreditation audits: `market_id`, `scope_edit_rule_set_id`, `state`, `outcome`.

### 2.4. The Logical Clock

Nothing in this domain reads wall-clock time. Enumeration due dates, household tenure, interval windows, universe vintage spacing, notification lead times, delivery service levels and lateness penalties all read a single server-held logical clock, and an administrative test-driving capability sets that clock to a supplied `current_utc` instant, answering with the value now in force as `current_utc` and the value it replaced as `previous_utc`. Before the first such call the clock reads exactly `2026-08-01T00:00:00Z`, rendered like every other instant in the canonical three-fractional-digit form `2026-08-01T00:00:00.000Z`; that startup default is fixed and must never fall back to real wall-clock time. The response carries those two fields alone — it is not a persisted resource and so has no `id`, `created_at` or `version` — and it answers HTTP 200.

The clock is monotonic. A request whose `current_utc` is earlier than the value currently in force is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422); setting it to exactly the value already in force is accepted, since the requirement is that the new value be greater than or equal to the current one. All seven roles may advance the clock, because every role's workflow needs to be able to move time forward.

### 2.5. Common Record Properties

Every resource in this system — markets, quota cells, universe estimates, households, meters, tuning intervals, editing rule sets, processing runs, household weights, clients, client deliverables, client notifications, methodology changes and accreditation audits alike — carries the same four system-managed properties:

- `id` — a server-minted UUID. It carries no type prefix and no embedded semantics.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the row was first written, taken from the logical clock.
- `updated_at` — an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the row, including mutations performed by a cascade the client did not directly request. It is read from the logical clock as it stands when the mutating request completes, so every row a single request moved carries one and the same stamp.
- `version` — an integer that starts at 1 on creation and increments by exactly 1 per request that mutates the row, however many times that request writes it: a cascade that reaches the same row through several links, or a handler that writes a field and then re-derives a roll-up on the same row, still advances the row by exactly 1. A request that ends in an error advances nothing at all.

Because roll-up fields are real fields, a change to a roll-up is a mutation: when a household's activation drives `intab_count` and `fill_rate` on its quota cell, the quota cell's `updated_at` and `version` both move; when the cell's status change in turn drives `under_target_cell_count` and `recruitment_posture` on the market, the market's `updated_at` and `version` both move too. Several endpoints are called out in §3 as advancing a parent's `version` for exactly this reason, and that advance is what the optimistic concurrency checks in §2.7 observe.

Timestamps that record a business event rather than a row edit — `recruited_at`, `installed_at`, `last_enumeration_at`, `published_at`, `superseded_at`, `sent_at`, `acknowledged_at`, `activated_at`, `finalized_at`, `delivered_at`, `posture_changed_at`, `notification_deadline_at` and `due_at` — are all read from the logical clock at the moment the event occurs, and are all rendered in the same ISO 8601 UTC form. Tenure and enumeration-deadline arithmetic reads `recruited_at`, never `created_at`.

### 2.6. Reference Resolution and the Validation Ladder

Every request walks a fixed ladder of generic checks before any endpoint-specific business rule is consulted, and the first failure on the ladder is the error the caller sees:

1. **Authentication** — headers present and the role recognised, else `ERR_UNAUTHENTICATED`.
2. **Authorisation** — the acting role appears on the target operation's role list, else `ERR_UNAUTHORIZED`.
3. **Client scoping** — a `ClientUser` acting on another client's deliverable or notification, else `ERR_UNAUTHORIZED`.
4. **Path existence** — every identifier embedded in the URL is resolved left to right, so the outer identifier is resolved before the inner one: `market_id` before `quota_cell_id`, `household_id` before `meter_id`, `methodology_change_id` before `client_notification_id`. The rejection names the first identifier that fails to resolve. The path identifiers used across the API are `market_id`, `quota_cell_id`, `universe_estimate_id`, `edit_rule_set_id`, `household_id`, `meter_id`, `tuning_interval_id`, `processing_run_id`, `household_weight_id`, `client_id`, `client_deliverable_id`, `client_notification_id`, `methodology_change_id` and `accreditation_audit_id`.
5. **Body reference existence** — every reference identifier carried in a request body must resolve to an existing row: `market_id`, `quota_cell_id`, `universe_estimate_id`, `edit_rule_set_id`, `processing_run_id`, `client_id`, `baseline_processing_run_id`, `target_edit_rule_set_id`, `proposed_edit_rule_set_id`, `scope_edit_rule_set_id`, `meter_id`, `household_id` and `supersedes_change_id`. The step applies to top-level reference identifiers only: a `quota_cell_id` carried inside a `cell_populations` entry is not resolved here, and one that names no existing cell surfaces later as the coverage failure `ERR_UNIVERSE_CELL_COVERAGE` rather than as a 404.
6. **Required inputs** — every input the operation declares as required is present, else `ERR_INVALID_REQUEST` (HTTP 422). A request body must be a JSON object: an absent or empty body is read as an empty object, so its required inputs simply fail this step, while a body that does not parse as JSON at all, or that parses to an array, a string or any other non-object, is itself refused with `ERR_INVALID_REQUEST` (HTTP 422) — never with a 400 or a 415. An input supplied as JSON `null` counts as absent. Inputs the operation does not declare are ignored.
7. **Value shapes** — every supplied value satisfies its declared enumeration membership, regular expression, numeric range and ISO 8601 shape, else `ERR_INVALID_REQUEST`. An integer input must be a JSON integer — a JSON boolean, a string spelling of a number and a fractional number are all refused — and a numeric input must be a JSON number, boolean spellings again refused. An ISO 8601 instant is accepted with or without seconds and with or without fractional digits, with either `T` or a space separating date from time, and with a `Z` designator, an explicit `±HH:MM` offset or no designator at all; `Z` and an absent designator are both read as UTC, an explicit offset is normalised to UTC before any comparison is made, and every stored instant is re-rendered in the canonical three-fractional-digit `Z` form regardless of how it arrived. This is where `market_code` must match a literal `DMA-` prefix followed by exactly three digits, `serial_no` must match a literal `MT-` prefix followed by exactly six digits, `vintage_label` must be four digits followed by the letter `Q` and a digit from 1 to 4, `target_households` must be at least 1, `roster_persons_count` must be between 1 and 12 inclusive, `tv_sets_count` must be between 0 and 8 inclusive, `tuning_minutes` must be at least 0 and must not exceed the whole minutes between `start_iso` and `end_iso`, and `outlier_weight_ratio_cap` must be at least 1.0. It is also where a manually supplied `hold_reason` of `UPSTREAM_RUN_REPIN` is refused, that reason being reserved for the cascade.
8. **Optimistic concurrency** — where the operation declares an expected-version input, the supplied value must equal the parent's current `version`, else the concurrency rule's error at HTTP 412 (see §2.7).
9. **Clock monotonicity** — for the clock-setting capability only, the supplied instant must not move the clock backwards, else `ERR_CLOCK_NOT_MONOTONIC`.

Failures at step 4 and step 5 are reported with the not-found error of the entity whose identifier failed: `ERR_MARKET_NOT_FOUND`, `ERR_QUOTA_CELL_NOT_FOUND`, `ERR_UNIVERSE_ESTIMATE_NOT_FOUND`, `ERR_EDIT_RULE_SET_NOT_FOUND`, `ERR_HOUSEHOLD_NOT_FOUND`, `ERR_METER_NOT_FOUND`, `ERR_TUNING_INTERVAL_NOT_FOUND`, `ERR_PROCESSING_RUN_NOT_FOUND`, `ERR_HOUSEHOLD_WEIGHT_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`, `ERR_CLIENT_DELIVERABLE_NOT_FOUND`, `ERR_CLIENT_NOTIFICATION_NOT_FOUND`, `ERR_METHODOLOGY_CHANGE_NOT_FOUND` or `ERR_ACCREDITATION_AUDIT_NOT_FOUND`, each at HTTP 404. A `baseline_processing_run_id` that does not resolve reports `ERR_PROCESSING_RUN_NOT_FOUND`; a `target_edit_rule_set_id`, `proposed_edit_rule_set_id` or `scope_edit_rule_set_id` that does not resolve reports `ERR_EDIT_RULE_SET_NOT_FOUND`; a `supersedes_change_id` that does not resolve reports `ERR_METHODOLOGY_CHANGE_NOT_FOUND`.

Two routing failures sit outside the ladder entirely, because they are settled before any handler is reached and therefore before authentication: a request whose path matches no endpoint declared in §4 is refused with `ERR_NOT_FOUND` (HTTP 404), and a path that is declared but is invoked with a method §4 does not declare for it is refused with `ERR_METHOD_NOT_ALLOWED` (HTTP 405). Both are rendered in the standard error envelope. A trailing slash is insignificant in matching, so `/markets/` and `/markets` reach the same endpoint.

Each §3 workflow states the order of its own business checks explicitly. Where a workflow lists checks "in this order", that ordering is normative: it decides which error a request that violates several rules at once actually receives.

### 2.7. Optimistic Concurrency on Pinned Parents

Three write operations reach across an aggregate boundary in a way that can silently destroy work the caller never observed, and all three are therefore guarded by an optimistic concurrency check against the parent's `version`.

Opening a processing run requires a non-optional `expected_market_version` input carrying the client's last observed `version` of the target `Market`. If that value does not equal the market's current `version`, the request is rejected with `ERR_STALE_MARKET_VERSION` (HTTP 412). The reason is concrete: run creation legitimately supersedes an earlier run of the same market that is still `OPEN`, `EDITED` or `PENDING_REPIN`, so a writer holding a stale view of the market would discard editing work it never saw.

Drafting a universe estimate likewise requires a non-optional `expected_market_version` matching the target `Market`'s current `version`, and a mismatch is rejected with `ERR_STALE_MARKET_VERSION` (HTTP 412). A newly published vintage supersedes the market's earlier published vintage and repins its open runs, so a writer working from a stale market view would retire a vintage it never saw.

Running an impact analysis on a methodology change requires a non-optional `expected_methodology_change_version` input matching that `MethodologyChange` row's current `version`; a mismatch is rejected with `ERR_STALE_METHODOLOGY_CHANGE_VERSION` (HTTP 412). A fresh analysis overwrites `impact_delta_pct`, `impact_tier` and `notification_lead_hours`, so a writer whose view predates a revision round would publish a delta computed against a retired proposal.

No other operation takes a version input. Endpoints not named above perform no concurrency check and must not require one.

### 2.8. Numeric Precision and Rounding

One rounding convention governs the entire system: **round half up**, applied at exactly the precision the rule names, and applied at each named step rather than only at the end.

- Rates and weights — `fill_rate`, `base_weight`, `adjusted_weight`, `total_weight_mass`, `run_compliance_rate`, `compliance_rate_rolling_30`, `impact_delta_pct`, `disclosed_delta_pct` and the `outlier_weight_ratio_cap` input — carry 4 decimal places.
- A household weight row's `contribution` carries 2 decimal places.
- Money is held in whole cents throughout: `incentive_budget_cents`, `incentive_budget_committed_cents`, `incentive_budget_reserved_cents`, `base_incentive_cents`, `incentive_accrued_cents`, `tier_base_fee_cents`, `delivery_sla_credit_cents`, `gross_cents`, `discount_cents`, `late_penalty_cents` and `total_cents` are all integers, and every intermediate money figure is rounded to a whole cent before the next step reads it.
- `effective_incentive_multiplier` is a ratio carried to 2 decimal places, taking the value 1.25 or 1.00.
- Counts, minutes and day figures — `intab_count`, `quota_cell_count`, `filled_cell_count`, `under_target_cell_count`, `open_audit_count`, `enumeration_count`, `fault_count`, `missing_minutes_last_scan`, `tuning_minutes`, `usable_minutes`, `window_minutes`, `days_late`, `revision_count`, `requested_cell_count`, `total_population_households`, `total_population_persons`, `intab_snapshot_count`, `contributing_household_count`, `ascribed_interval_count`, `invalidated_interval_count`, `outlier_household_count`, `excluded_cell_count`, `projected_average_audience`, `baseline_projected_average_audience`, `notification_lead_hours`, `notified_client_count`, `acknowledged_client_count`, `held_deliverable_count`, `custom_analysis_quota`, `custom_analysis_used`, `delivery_sla_hours`, `persons_count`, `roster_persons_count`, `tv_sets_count`, `dma_rank`, `target_households` and the rule-set bounds `missing_interval_ascription_minutes`, `invalid_tuning_max_minutes`, `outlier_household_minutes_cap` and `fault_missing_minutes_threshold` — are integers.

Where a rule measures elapsed time it says so precisely: household tenure and enumeration age are floors of whole units, and delivery lateness is a ceiling of whole days, so any lateness at all counts as a full day. Monetary and count values are returned in response bodies as JSON numbers, never as strings. The declared scales above govern the precision a value is rounded to, not the way it is spelled on the wire: every rate, weight, ratio and contribution is emitted as a plain JSON number with no trailing-zero padding, so a `fill_rate` of 0.0000 is rendered `0.0` and an `effective_incentive_multiplier` of 1.00 is rendered `1.0`.

### 2.9. Cascade Discipline and Conserved Quantities

Many operations in this domain mutate more than one row. The platform treats those secondary movements as part of the operation, not as eventual consequences: they are applied immediately, in the order the workflow states, within the same request. Three consequences follow, and they are contractual.

**Cascades are ordered and numbered.** Where §3 describes a cascade as a chain of links, the links execute in the stated sequence, because a later link reads what an earlier link wrote. A meter fault, for instance, first changes the device, then the household, then the quota cell, then the cell's incentive posture, then the market's roll-ups and posture — and the market's posture is computed from cell statuses that the third and fourth links have already updated.

**Conditional links are genuinely conditional.** A link whose precondition does not hold is skipped, and skipping it does not abort the links that follow it. Retiring a household moves only those meters that are currently `INSTALLED`; meters already `REMOVED` are untouched, and meters still `SHIPPED` are untouched. Cancelling notifications on a revision touches only notifications still in `SENT`; those already `ACKNOWLEDGED` survive unchanged.

**Compensating moves restore conserved quantities exactly.** Three quantities in this system are conserved by construction, and every operation that moves one has an exact counterpart that moves it back:

- A quota cell's `intab_count` is, at all times, precisely the number of households of that cell whose `status` is `ACTIVE`. A household leaving in-tab and returning leaves the count exactly where it started.
- A market's `incentive_budget_committed_cents` is, at all times, precisely the sum of `incentive_accrued_cents` over every household of that market, whatever their status — including retired households, whose accruals are never clawed back.
- A market's `incentive_budget_reserved_cents` is, at all times, precisely the sum, over the market's quota cells whose `incentive_boost_active` is true, of the boost reservation for that cell. Arming and disarming a boost moves the same amount in and out.

### 2.10. Segregation of Duties

Three approval gates require two distinct operators, and all three report the same rejection, `ERR_SEGREGATION_OF_DUTIES` (HTTP 409):

- Publishing a processing run requires an `X-User-ID` different from the run's `opened_by_user_id`.
- Finalizing an accreditation audit requires an `X-User-ID` different from the audit's `opened_by_user_id`.
- Activating a methodology change requires an `X-User-ID` different from the change's `created_by_user_id`.

The comparison is on the acting `X-User-ID` alone; the role is already fixed by the endpoint's authorisation list, so this is a second, independent check on top of it.

### 2.11. Accreditation Gates and Disclosure Persistence

Accreditation status is the highest-precedence consideration in the system, and it acts on two separate levers.

The first lever is the panel itself. Opening an accreditation audit against a market raises that market's `open_audit_count`, which drives `recruitment_posture` to `FROZEN` ahead of every other consideration. While a market is `FROZEN`, no household may be recruited into it, no meter may be shipped into it, no household in it may be enumerated in or out of tab, and no processing run of it may be published. Finalizing the audit lowers `open_audit_count` again and re-evaluates the posture, releasing the freeze when no other audit of that market is open.

The second lever is publication. A `DENIED` outcome sets the market's `publication_blocked` to true, and while that flag stands, no run of that market may be published no matter who calls and no matter how ready the run is. An `ACCREDITED` or `QUALIFIED` outcome sets the flag to false. A `QUALIFIED` or `DENIED` outcome additionally appends its stated limitations onto the market's `limitation_disclosures`, and those disclosures are permanent: a later clean `ACCREDITED` audit leaves the accumulated list exactly as it was, so a limitation once recorded is never erased. Every run published after a disclosure is recorded carries a copy of the market's disclosures on the run itself, so the caveat travels with the data.

## 3. Business Logic & Workflows

### 3.1. Markets, Quota Cells and the Recruitment Posture Gate

A **Market** is a designated market area — the geographic unit a panel is built and reported for. A `PanelOperationsManager` registers one by supplying a `name` between 1 and 120 characters, a `market_code` unique across all markets, a `dma_rank` of at least 1 (a smaller rank means a larger market), and an `incentive_budget_cents` of at least 0 authorising the market's total cooperation-incentive spend. A `market_code` that duplicates an existing market's code is refused with `ERR_INVALID_REQUEST`.

A market carries a set of roll-ups the server maintains and clients never write. `quota_cell_count` is the number of quota cells belonging to the market; `filled_cell_count` is the number of those cells whose `quota_status` is `FILLED`; `under_target_cell_count` is the number whose `quota_status` is `UNDER_TARGET`; `open_audit_count` is the number of accreditation audits of the market whose `state` is `OPEN`. `incentive_budget_committed_cents` is the sum of `incentive_accrued_cents` across every household of the market regardless of household status, and `incentive_budget_reserved_cents` is the sum of the boost reservations of the market's cells whose `incentive_boost_active` is true. `accreditation_status` starts at `UNAUDITED` and thereafter holds the outcome of the most recently finalized audit — `ACCREDITED`, `QUALIFIED` or `DENIED`. `publication_blocked` starts false. `limitation_disclosures` starts as an empty array and only ever grows.

**Recruitment posture.** The single most consequential derived field on a market is `recruitment_posture`, which takes one of `OPEN`, `RESTRICTED`, `CLOSED` or `FROZEN`. It is evaluated by walking four clauses in exactly this order, and the first clause that matches wins:

1. If the market has at least one accreditation audit in state `OPEN` — that is, `open_audit_count` is 1 or more — the posture is `FROZEN`.
2. Otherwise, if the market has at least one quota cell and every one of its quota cells is `FILLED` — that is, `filled_cell_count` equals `quota_cell_count` and `quota_cell_count` is at least 1 — the posture is `CLOSED`.
3. Otherwise, if none of the market's quota cells is `UNDER_TARGET` — that is, `under_target_cell_count` is exactly 0 — the posture is `RESTRICTED`.
4. Otherwise the posture is `OPEN`.

Note the consequence for a brand-new market: it has no quota cells at all, so `under_target_cell_count` is 0, clause 3 fires before clause 4, and the initial posture is `RESTRICTED` rather than `OPEN`. Posture is re-evaluated at market registration and thereafter on every change to `open_audit_count` and on every change to the `quota_status` of any of the market's cells. `posture_changed_at` is stamped from the logical clock at registration and thereafter only when an evaluation actually produces a value different from the stored one; an evaluation that confirms the existing value leaves the stamp alone.

**Quota cells.** A `PanelOperationsManager` divides a market into **quota cells**, each of which is one demographic-by-geographic stratum: an `age_band` of `P18_34`, `P35_54` or `P55_PLUS`, an `income_band` of `LOW`, `MID` or `HIGH`, and a `geo_zone` of `URBAN`, `SUBURBAN` or `RURAL`. The cell also carries a `target_households` recruitment quota of at least 1 and a `base_incentive_cents` per-period cooperation incentive of at least 0. Two checks guard the creation, evaluated in this order: first the incentive-budget headroom check described in §3.4, which rejects with `ERR_INCENTIVE_BUDGET_EXCEEDED` if the boost reservation the new cell is about to take would push the market's committed plus reserved cents past `incentive_budget_cents`; then the uniqueness check, which rejects with `ERR_QUOTA_CELL_DUPLICATE` if the market already holds a cell with the same combination of `age_band`, `income_band` and `geo_zone`.

A newly created cell is empty, and the fill calculation therefore lands it in its most aggressive recruitment stance: `intab_count` 0, `fill_rate` 0.0000, `quota_status` `UNDER_TARGET`, `incentive_boost_active` true and `effective_incentive_multiplier` 1.25. That armed boost immediately reserves budget on the parent market, the market's `quota_cell_count` and `under_target_cell_count` each rise by one, the posture is re-evaluated — which moves a market holding its first cell from `RESTRICTED` to `OPEN`, because clause 3 no longer matches — and the market's `version` advances by one.

**The fill calculation.** Whenever a cell's `intab_count` changes, the cell is re-graded. `intab_count` is recounted as the number of households of that cell whose `status` is exactly `ACTIVE`; households in `RECRUITED`, `INSTALL_SCHEDULED`, `ENUM_PENDING`, `FAULT_HOLD`, `NONCOMPLIANT_HOLD` or `RETIRED` are all excluded. `fill_rate` is then the in-tab count divided by `target_households`, rounded half up to 4 decimal places. The status follows from the rate: `FILLED` when the rate is 1.0000 or more, `ON_TARGET` when the rate is 0.8000 or more but below 1.0000, and `UNDER_TARGET` in every other case.

The same calculation arms and disarms the cooperation incentive boost, and it does so only on a genuine change of stance. When the graded status is `UNDER_TARGET` and the cell's boost is not already armed, `incentive_boost_active` becomes true, `effective_incentive_multiplier` becomes 1.25, and the market's `incentive_budget_reserved_cents` rises by the cell's `base_incentive_cents` multiplied by one quarter and by `target_households`, rounded half up to a whole cent. When the graded status is anything other than `UNDER_TARGET` and the cell's boost is currently armed, `incentive_boost_active` becomes false, `effective_incentive_multiplier` returns to 1.00, and the market's `incentive_budget_reserved_cents` falls by that same figure, computed the same way. Because the reservation is recomputed from the cell's own `base_incentive_cents` and `target_households` each time, arming and disarming are exact inverses.

**Moving the budget.** A `PanelOperationsManager` may raise or lower a market's authorised spend by submitting a signed `delta_cents` — any integer, positive, negative or zero — together with a required `memo` of 1 to 400 characters recording why. The market's `incentive_budget_cents` moves by that delta and the market's `version` advances by one; the adjustment touches no other market field, so neither the roll-ups nor `recruitment_posture` are re-derived by it. A reduction that would leave `incentive_budget_cents` below the market's already committed plus reserved cents is refused with `ERR_INCENTIVE_BUDGET_EXCEEDED` — authorisation may be withdrawn only down to what has actually been spoken for.

### 3.2. Household Recruitment and the Enumeration Verdict

Recruiting a **Household** is the act of adding one metered home to a quota cell, and it is a `PanelOperationsManager` responsibility. The payload names the `market_id` and the `quota_cell_id` the home will fill, the `recruitment_source` that produced the contact — `ADDRESS_SAMPLE`, `RDD_PHONE` or `ONLINE_PANEL_TRANSFER` — and a `persons_count` of at least 1 recording how many people the recruiter found living there. Three business checks run in this order:

1. The market's `recruitment_posture` must be neither `CLOSED` nor `FROZEN`; otherwise intake stops with `ERR_RECRUITMENT_CLOSED`. A fully filled market and a market under accreditation audit are both closed to intake, and this gate fires before any cell-level consideration.
2. The referenced quota cell's own market must be the market named in the same payload, otherwise `ERR_QUOTA_CELL_MARKET_MISMATCH`.
3. The referenced cell's `quota_status` must not be `FILLED`, otherwise `ERR_QUOTA_CELL_FILLED`. A cell at `ON_TARGET` still has room; a cell at `FILLED` does not.

A recruited household begins at `status` `RECRUITED` with `recruited_at` stamped from the logical clock — this, and not `created_at`, is what the tenure multiplier and the first-enumeration deadline later measure from. `enumeration_verdict` starts at `PENDING`, `enumeration_count` at 0, `compliance_rate_rolling_30` at 0.0000, `incentive_accrued_cents` at 0 with an empty `accrual_periods` array, and `roster_persons_count`, `tv_sets_count`, `last_enumeration_at` and `retired_reason` all null. Recruitment alone does not put a household in tab: the cell's `intab_count` does not move.

**The household lifecycle.** A household's `status` walks `RECRUITED`, `INSTALL_SCHEDULED`, `ENUM_PENDING`, `ACTIVE`, `FAULT_HOLD`, `NONCOMPLIANT_HOLD` and `RETIRED`, with `RETIRED` terminal. There is no separate activation call: metering moves the home from `RECRUITED` to `INSTALL_SCHEDULED` and then to `ENUM_PENDING` (see §3.3), and the **enumeration verdict itself** is what carries the home in and out of the in-tab sample.

**Enumeration.** A `FieldTechnician` records an enumeration visit by submitting the household roster head-count as `roster_persons_count` and the number of television sets found as `tv_sets_count`. Four checks run in this order:

1. The household's `status` must be `ENUM_PENDING`, `ACTIVE` or `NONCOMPLIANT_HOLD`, otherwise `ERR_HOUSEHOLD_NOT_ENUMERABLE`. Re-enumerating an active or held home is normal practice; enumerating a home that has not yet had a tuner installed, or one that has been retired, is not.
2. The household must hold at least one meter whose `meter_type` is `TV_TUNER` and whose `install_status` is `INSTALLED`, otherwise `ERR_NO_INSTALLED_METER`. A home metered only for streaming or out-of-home cannot be enumerated.
3. At least one of those installed tuners must have `health_status` `HEALTHY`, otherwise `ERR_METER_FAULTED`. A home whose only tuner is `FAULTED` or `SUSPECT` must be repaired first, because a compliant verdict would otherwise place a blind household in tab.
4. The market's `recruitment_posture` must not be `FROZEN`, otherwise `ERR_MARKET_FROZEN`. An open accreditation audit stops movement in *both* directions: while the market is frozen no household may be enumerated into tab and none may be enumerated out of it.

The verdict is then computed from the submission alone — no other household and no other entity participates. Let the sequence number of this submission be the household's `enumeration_count` plus one. The roster test passes when the submitted `roster_persons_count` equals the household's recorded `persons_count` exactly. The sets test passes when the submitted `tv_sets_count` is at least 1. The timeliness test applies only to the household's very first submission: for that first visit, the household's age in whole days is the elapsed time from `recruited_at` to the current logical clock divided by 86400 seconds and floored to a whole number of days, and the test passes when that age is at most 14 days — an age of exactly 14 days is still on time. Every later submission passes the timeliness test unconditionally, because re-enumerations carry no due date. The verdict is `COMPLIANT` when all three tests pass and `NONCOMPLIANT` when any of them fails.

Whatever the verdict, `enumeration_count` rises by one and `roster_persons_count`, `tv_sets_count`, `enumeration_verdict` and `last_enumeration_at` are refreshed from the submission and the clock. The status movement then depends on where the household stood and what the verdict was, and there are exactly four cases:

- `ENUM_PENDING` with a `COMPLIANT` verdict moves the household to `ACTIVE`. This transition additionally requires that the household hold at least one meter that is a `TV_TUNER`, `INSTALLED` and `HEALTHY`, and that the market not be `FROZEN`. Its cell's `intab_count` rises by one, the fill calculation re-grades the cell, and the market's posture is recomputed.
- `ENUM_PENDING` with a `NONCOMPLIANT` verdict moves the household to `NONCOMPLIANT_HOLD` and changes no in-tab count, because the household was never in tab.
- `ACTIVE` with a `NONCOMPLIANT` verdict moves the household to `NONCOMPLIANT_HOLD`, drops its cell's `intab_count` by one, re-grades the cell, and recomputes the market posture.
- `NONCOMPLIANT_HOLD` with a `COMPLIANT` verdict returns the household to `ACTIVE` — again requiring at least one `INSTALLED` and `HEALTHY` `TV_TUNER` — raising the cell's `intab_count` by one, re-grading the cell and recomputing the posture. The cycle `ACTIVE → NONCOMPLIANT_HOLD → ACTIVE` therefore returns `intab_count` to precisely its pre-hold value.

Every other combination of prior status and verdict leaves `status` exactly where it was: an `ACTIVE` household re-confirmed `COMPLIANT` stays `ACTIVE`, and a `NONCOMPLIANT_HOLD` household confirmed `NONCOMPLIANT` again stays held. Neither moves any `intab_count`, though both still refresh the submission fields, `enumeration_count` and `last_enumeration_at`.

**Retirement.** A `PanelOperationsManager` retires a household permanently by supplying a required `retired_reason` of 1 to 400 characters, which is stored on the row. Retirement is admitted from any status except `RETIRED` itself; a household already in the terminal status is refused with `ERR_HOUSEHOLD_ALREADY_RETIRED`. The household's `status` becomes `RETIRED`, and every meter of the household whose `install_status` is `INSTALLED` moves to `REMOVED` — a conditional cascade, so meters still `SHIPPED` and meters already `REMOVED` are untouched. If, and only if, the household was `ACTIVE` at the moment of retirement, its cell's `intab_count` falls by one, the cell is re-graded and the market posture is recomputed. What retirement never does is claw money back: unreversed entries in `accrual_periods` stay on the ledger, `incentive_accrued_cents` is left exactly as it stands, and the market's `incentive_budget_committed_cents` is therefore unchanged by retirement. `RETIRED` is terminal in the strict sense — no later enumeration, incentive accrual, meter shipment or meter removal is accepted against the household.

### 3.3. Meter Deployment, Health Monitoring and the Fault Cascade

A **Meter** is one physical collection device deployed to a household. It carries a `household_id`, a `meter_type` of `TV_TUNER`, `STREAMING_ROUTER` or `PORTABLE_OOH`, and a `serial_no` matching the pattern `MT-` followed by exactly six digits.

The essential structural point about a meter is that it tracks **two entirely independent status dimensions**. `install_status` describes where the device physically is and walks `SHIPPED` to `INSTALLED` to `REMOVED`, with `REMOVED` terminal. `health_status` describes whether the device is delivering trustworthy data and cycles `HEALTHY`, `SUSPECT` and `FAULTED` with no terminal value at all. Neither dimension constrains the other's stored value: a `REMOVED` meter retains whatever `health_status` it had when it was pulled, and a `FAULTED` meter is still `INSTALLED` until someone removes it. Every operation below states which dimension it moves.

**Shipping.** A `FieldTechnician` ships a device by naming the household, the type and the serial. Four checks run in this order:

1. The household's `status` must be `RECRUITED` or `INSTALL_SCHEDULED`, otherwise `ERR_HOUSEHOLD_NOT_ACCEPTING_METERS`. A household past enumeration takes no new devices through this route.
2. `serial_no` must be unique across every meter row ever created, including `REMOVED` ones, otherwise `ERR_METER_SERIAL_DUPLICATE`.
3. The household must hold no other meter of the same `meter_type` whose `install_status` is `SHIPPED` or `INSTALLED`, otherwise `ERR_METER_TYPE_ALREADY_PRESENT`. A `REMOVED` device of that type does not block a replacement, which is exactly how an equipment swap is performed.
4. The market's `recruitment_posture` must not be `FROZEN`, otherwise `ERR_MARKET_FROZEN`.

Note the ordering consequence: a duplicate serial in a frozen market is reported as the duplicate, because the serial check is evaluated before the freeze check. A shipped meter starts at `install_status` `SHIPPED`, `health_status` `HEALTHY`, `fault_count` 0, `missing_minutes_last_scan` 0, and `installed_at` and `last_fault_code` both null. Shipping is also the *only* thing that schedules an installation: when the household was `RECRUITED`, creating its first meter row moves the household to `INSTALL_SCHEDULED`. There is no separate scheduling call. A second or third meter shipped to a household that has already moved on leaves the household `status` untouched.

**Install confirmation.** A `FieldTechnician` confirms physical installation with no payload at all; the endpoint reads no body, so anything sent as one is ignored rather than validated. The meter's `install_status` must be `SHIPPED`, otherwise `ERR_METER_NOT_SHIPPED`. The dimension moves to `INSTALLED` and `installed_at` is stamped from the logical clock. Only a `TV_TUNER` advances the home: when the confirmed device is a `TV_TUNER` and the household is `INSTALL_SCHEDULED`, the household moves to `ENUM_PENDING` and enumeration becomes possible. Confirming a `STREAMING_ROUTER` or a `PORTABLE_OOH` device never changes the household `status`. Installation alone never puts a household in tab, so no `intab_count` moves here.

**Fault reports and the five-link cascade.** A `FieldTechnician` reports a field-detected fault by supplying a `fault_code` of `NO_SIGNAL`, `POWER_LOSS`, `TAMPER`, `CLOCK_DRIFT` or `MISSING_INTERVALS`. The device's `health_status` must be `HEALTHY` or `SUSPECT`, otherwise `ERR_METER_ALREADY_FAULTED` — the same fault cannot be reported twice without an intervening repair. The report also requires the device to be `INSTALLED`, otherwise `ERR_METER_NOT_INSTALLED`; the health check is evaluated first, so an already-`FAULTED` device that has since been pulled from the field reports `ERR_METER_ALREADY_FAULTED` rather than `ERR_METER_NOT_INSTALLED`.

The report itself is link 1 of a five-link cascade: `health_status` becomes `FAULTED`, `fault_count` rises by one, and `last_fault_code` is set to the submitted code. The remaining links fire only under a narrow condition, and getting that condition right is the whole point of the cascade:

- **Link 2** applies only when the newly faulted device's `meter_type` is `TV_TUNER` *and*, after the change, the household holds zero meters that are simultaneously `TV_TUNER`, `INSTALLED` and `HEALTHY`. When both hold and the household is `ACTIVE`, the household moves to `FAULT_HOLD`. A faulted streaming router, or a faulted tuner at a home that still has a second healthy installed tuner, stops the cascade dead at link 1.
- **Link 3**: the household's quota cell has `intab_count` reduced by one and the fill calculation re-grades the cell.
- **Link 4** applies only when that re-grading actually moved the cell's `quota_status` to `UNDER_TARGET`: the cell's `incentive_boost_active` becomes true, `effective_incentive_multiplier` becomes 1.25, and the market's `incentive_budget_reserved_cents` rises by `base_incentive_cents` multiplied by one quarter and by `target_households`, rounded half up to a whole cent.
- **Link 5**: the market's `filled_cell_count` and `under_target_cell_count` are recomputed, the recruitment posture is re-evaluated, and `posture_changed_at` is stamped only if the posture value actually changed.

**Repairs.** A `FieldTechnician` clears a fault by supplying a required `repair_note` of 1 to 400 characters, which is not stored on the row. The device's `health_status` must be `FAULTED` or `SUSPECT` and its `install_status` must not be `REMOVED`, otherwise `ERR_METER_NOT_FAULTED` — a healthy device has nothing to repair. The repair sets `health_status` to `HEALTHY`, clears `last_fault_code` back to null and resets `missing_minutes_last_scan` to 0. What it does **not** do is undo `fault_count`, which is a lifetime counter and only ever rises.

The repair is the exact compensating counterpart of the fault cascade. When the repaired device is a `TV_TUNER` with `install_status` `INSTALLED`, the household is in `FAULT_HOLD`, and the household's `enumeration_verdict` is still `COMPLIANT`, the household returns to `ACTIVE`, its cell's `intab_count` rises by one and the cell is re-graded; when that re-grading moves the cell out of `UNDER_TARGET`, `incentive_boost_active` becomes false, `effective_incentive_multiplier` returns to 1.00 and the market's `incentive_budget_reserved_cents` falls by the same quarter-of-base figure; then the market roll-ups and posture are recomputed. Because both directions compute the reservation from the cell's own stored numbers, a fault followed by a repair returns `intab_count` and `incentive_budget_reserved_cents` to precisely their pre-fault values. A household in `FAULT_HOLD` whose `enumeration_verdict` had turned `NONCOMPLIANT` is not restored by a repair; it must be re-enumerated.

**Removals.** A `FieldTechnician` decommissions a device by supplying a required `removal_note` of 1 to 400 characters, which is likewise not stored on the row. Two checks run in this order: the meter's `install_status` must be `INSTALLED`, otherwise `ERR_METER_NOT_INSTALLED`; and the owning household's `status` must be one of `INSTALL_SCHEDULED`, `ENUM_PENDING`, `NONCOMPLIANT_HOLD` or `FAULT_HOLD`, otherwise `ERR_HOUSEHOLD_IN_TAB`. An `ACTIVE` household must be taken out of tab before its equipment can be pulled, and a `RETIRED` household's meters were already removed by the retirement cascade. Removal sets `install_status` to `REMOVED` and deliberately leaves `health_status` and `fault_count` exactly as they were — removal is not a repair. No household `status` and no `intab_count` moves, which is precisely why the household must already be out of tab. The freed `meter_type` slot becomes available, so a replacement device of the same type may be shipped.

**Automated fault detection.** A `MethodologyStatistician` may run a coverage scan against an open processing run; the run's `state` must be `OPEN`, otherwise `ERR_RUN_NOT_OPEN`. The scan visits every `INSTALLED` meter belonging to a household of the run's market, in meter `created_at` ascending order, and, for each, computes the coverage shortfall inside the run window. The covered minutes are the sum of `tuning_minutes` over that meter's tuning intervals whose `state` is `RAW`, `EDITED` or `ASCRIBED` and whose `start_iso` is at or after the run's `window_start_iso` and whose `end_iso` is at or before the run's `window_end_iso`; `INVALIDATED` records contribute nothing. The missing minutes are the run's `window_minutes` less the covered minutes, floored at 0 so a meter that over-reports is never credited with negative shortfall. The suspect floor is the rule set's `fault_missing_minutes_threshold` divided by two and rounded half up to a whole number.

Both comparisons are inclusive at the bottom. Missing minutes at or above `fault_missing_minutes_threshold` drive `health_status` to `FAULTED` with `last_fault_code` set to `MISSING_INTERVALS` and `fault_count` raised by one — but only for a device that is not already `FAULTED`; re-scanning one that is already `FAULTED` re-records its `missing_minutes_last_scan` and nothing else, leaving `fault_count` and whatever `last_fault_code` it already carries alone and firing no cascade a second time. A meter missing exactly the threshold is faulted, and one minute less is `SUSPECT`. Missing minutes at or above the suspect floor but below the threshold drive `health_status` to `SUSPECT`; a meter already `FAULTED` is not softened to `SUSPECT` or `HEALTHY` by a scan, since the scan only ever escalates. Missing minutes below the suspect floor leave `health_status` unchanged. Every scanned meter's `missing_minutes_last_scan` is updated regardless of the verdict, and `compliance_rate_rolling_30` is refreshed for every household that owned at least one of the scanned meters — a household of the market holding no `INSTALLED` meter at all is never visited, so its stored rate is left exactly as it stands.

The scan's `state` self-transition leaves the run in `OPEN` — nothing about the run itself moves, and the response body is that run row, returned unchanged — but every meter it drives to `FAULTED` fires cascade links 2 through 5 exactly as a hand-filed fault report would. A single fault-detection scan can therefore drop several households to `FAULT_HOLD`, re-arm several incentive boosts, and change a market's `recruitment_posture` without anyone having touched a household.

### 3.4. Cooperation Incentives

Panellists are paid a per-period cooperation incentive, and the money is tracked in two places: on the household as an audit ledger, and on the market as a budget commitment.

**Accrual.** A `PanelOperationsManager` accrues one payment period by supplying a required `period_label` of 1 to 40 characters, an opaque string the platform never parses. Three checks run in this order:

1. The market's `incentive_budget_committed_cents` plus its `incentive_budget_reserved_cents` plus the amount about to be committed must not exceed `incentive_budget_cents`, otherwise `ERR_INCENTIVE_BUDGET_EXCEEDED`. The amount about to be committed is the accrual the calculation below produces, so the figure must be computed before the headroom can be judged.
2. The household's `status` must be `ACTIVE`, otherwise `ERR_HOUSEHOLD_NOT_ACTIVE`. Only in-tab homes earn.
3. The household must hold no existing `accrual_periods` entry with the supplied `period_label` whose `reversed` flag is false, otherwise `ERR_INCENTIVE_PERIOD_ALREADY_ACCRUED`. A period that was accrued and then reversed becomes accruable again.

The amount is computed in nine numbered steps, and **each step rounds to whole cents before the next step reads its result**. Rounding is round half up throughout. Summing unrounded components and rounding once at the end produces a different figure and is wrong.

1. The tenure in months is the elapsed time from the household's `recruited_at` to the current logical clock, divided by 2592000 seconds and floored — thirty-day months.
2. The tenure multiplier is 1.000 for a tenure under 6 months, 1.075 for a tenure of 6 months or more but under 24, and 1.150 for a tenure of 24 months or more.
3. The cell base is the quota cell's `base_incentive_cents` multiplied by the cell's `effective_incentive_multiplier`, rounded to a whole cent. A cell with an armed boost therefore pays a quarter more before tenure is even considered.
4. The tenure amount is the cell base multiplied by the tenure multiplier, rounded to a whole cent.
5. The compliance bonus is 8.55 percent of the **rounded** tenure amount, rounded to a whole cent, and applies only when the household's `compliance_rate_rolling_30` is 0.90 or more; otherwise it is 0.
6. The out-of-home supplement is 4.05 percent of the same **rounded** tenure amount, rounded to a whole cent, and applies only when the household holds at least one meter whose `meter_type` is `PORTABLE_OOH` with `install_status` `INSTALLED`; otherwise it is 0.
7. The gross is the tenure amount plus the compliance bonus plus the out-of-home supplement.
8. The fault penalty is 25 percent of that gross, rounded to a whole cent, and applies only when the household holds at least one meter whose `health_status` is `FAULTED`; otherwise it is 0. Note that this looks only at health and not at installation, so a faulted device still on the books penalises the period.
9. The period amount is the lesser of the gross minus the penalty and the hard per-period cap of 5000 cents.

The accrual then appends an entry to `accrual_periods` holding the `period_label`, the `accrued_cents` just computed, and `reversed` set to false; raises the household's `incentive_accrued_cents` by that amount; and raises the market's `incentive_budget_committed_cents` by the same amount.

**Reversal.** A `PanelOperationsManager` reverses a period by supplying its `period_label` of 1 to 40 characters and a required `memo` of 1 to 400 characters recording why — typically an audit finding that the compliance figure used was wrong. The household's `accrual_periods` must hold an entry with that label whose `reversed` flag is false, otherwise `ERR_INCENTIVE_PERIOD_NOT_ACCRUED`; that entry is the only check the reversal makes, so reversal is admitted whatever the household's current `status`, `RETIRED` included — the terminal-status bar covers fresh accruals, not the correction of an old one. The matching entry's `reversed` flag becomes true and it keeps its `accrued_cents` for the audit trail — nothing is ever deleted from the ledger. The household's `incentive_accrued_cents` falls by exactly that entry's amount and the market's `incentive_budget_committed_cents` falls by the same, so both figures return to their pre-accrual values with no drift. The `period_label` becomes accruable again, and a re-accrual is computed fresh from the household's current tenure, compliance and equipment — it is not a replay of the reversed figure.

### 3.5. Population Universes and Editing Rule Sets

Two version-pinned reference objects govern every processing run: the population universe the run projects to, and the editing rule set the run's decisions are made under. Both are drafted, published and superseded, and a supersession reaches downstream into runs and even into client deliverables.

**Drafting a universe vintage.** A `MethodologyStatistician` drafts a **UniverseEstimate** for a market by supplying a `vintage_label` matching four digits followed by `Q` and a digit 1 through 4, an `effective_from` and an `effective_to` bounding the vintage's effectivity, a `cell_populations` array, and the `expected_market_version` pinning the market state the caller believes it read. `cell_populations` must be an array, and each entry is an object holding a non-empty string `quota_cell_id`, an integer `population_households` of at least 1, and an integer `population_persons` of at least 0. An entry that is not an object, or that breaks any one of those three shapes, is refused with `ERR_INVALID_REQUEST` as a shape failure at step 7 of the §2.6 ladder — that is, before any of the four business checks below, the concurrency check included. Four checks run in this order:

1. The optimistic-concurrency check on `expected_market_version` described in §2.7, which rejects a stale read with `ERR_STALE_MARKET_VERSION`.
2. `cell_populations` must name every quota cell of the target market exactly once — no cell omitted, no duplicate `quota_cell_id`, and no cell belonging to another market — otherwise `ERR_UNIVERSE_CELL_COVERAGE`. A market whose cells changed since the caller read them will therefore fail either this check or the concurrency check above it. The rule is an exact set equality and nothing more, so a market that holds no quota cells at all is satisfied by an empty `cell_populations` array and yields a draft whose two population totals are both 0.
3. `effective_from` must be strictly before `effective_to`, otherwise `ERR_INVALID_WINDOW`.
4. The pair of market and `vintage_label` must be unique across universe estimates in **any** status, including `SUPERSEDED` ones, otherwise `ERR_UNIVERSE_VINTAGE_DUPLICATE`.

The draft is created with `status` `DRAFT`, `published_at` and `superseded_at` null, and `total_population_households` and `total_population_persons` summed from the array entries. Drafting also advances the parent market's `version` by one, which is what makes two concurrent draft attempts against the same market mutually exclusive.

**Publishing a vintage.** The estimate's `status` must be `DRAFT`, otherwise `ERR_UNIVERSE_NOT_DRAFT`. At least 28 whole days must have elapsed between the `published_at` of every vintage of the same market currently standing in `PUBLISHED` and the logical clock at this call, otherwise `ERR_UNIVERSE_VINTAGE_TOO_SOON` — universe estimates are not allowed to churn. The bar is applied to each such vintage in turn rather than to a single "current" one, so where the supersession rule below has left two published vintages side by side the more recent of them governs. Exactly 28 whole days is enough; the elapsed figure is floored to whole days. A market with no published vintage yet has no such waiting period. Publishing also requires that every `quota_cell_id` in `cell_populations` still resolve to a quota cell of the estimate's market.

Publication sets `status` to `PUBLISHED` with `published_at` stamped from the clock, and then supersedes the past: every other universe estimate of the same market whose `status` is `PUBLISHED` and whose `effective_from` is earlier than this estimate's `effective_from` moves to `SUPERSEDED` with `superseded_at` stamped. `SUPERSEDED` is terminal. The supersession then cascades twice: every processing run of that market still pinned to a now-superseded estimate and standing in `OPEN`, `EDITED` or `WEIGHTED` is forced to `PENDING_REPIN` with `repin_required_reason` `UNIVERSE_SUPERSEDED`; and every client deliverable of one of those runs standing in `SCHEDULED`, `REQUESTED`, `IN_PROGRESS` or `REVISION_REQUESTED` is moved to `HELD` with `hold_reason` `UPSTREAM_RUN_REPIN` and `held_from_state` recording exactly where it stood — a row already `HELD` and a row already `DELIVERED` are each left alone. The runs are walked in run `created_at` ascending order and the deliverables in deliverable `created_at` ascending order, and each hold this cascade takes raises the owning client's `held_deliverable_count` by one and its `delivery_sla_credit_cents` by 5 percent of that client's `tier_base_fee_cents` rounded half up to a whole cent, exactly as §3.8 prescribes for that reserved reason. A run caught by this cascade in `WEIGHTED` keeps its household weight rows, its `weight_variant`, its `total_weight_mass` and its `projected_average_audience` untouched — unlike the activation cascade of §3.9, a reference-object publication only stalls the run, it does not tear its weighting down; the re-pin of §3.7 is what discards the downstream artefacts. A single publication can therefore stall a client's pipeline, which is why the reason code is reserved to the system and rejected when a caller tries to supply it by hand.

**Drafting an editing rule set.** An **EditRuleSet** is drafted by a `MethodologyStatistician` and carries a globally unique `label` of 1 to 60 characters — a `label` duplicating that of any existing rule set, whatever its `status`, is refused with `ERR_INVALID_REQUEST` — plus five thresholds: `missing_interval_ascription_minutes`, the maximum gap in minutes between two consecutive same-meter intervals that the edit pass will fill with a synthetic record, at least 0 and at most 240; `invalid_tuning_max_minutes`, at least 1, above which a raw record is invalidated; `outlier_household_minutes_cap`, at least 1, above which a household's whole contribution is treated as an outlier; `outlier_weight_ratio_cap`, a number of at least 1.0000 held to 4 decimal places, being the multiple of the run's mean base weight above which a household weight is capped; and `fault_missing_minutes_threshold`, at least 1, being the coverage shortfall at which a meter is faulted. A new rule set is `DRAFT` with `published_at` null.

**Publishing a rule set.** The rule set's `status` must be `DRAFT`, otherwise `ERR_RULE_SET_NOT_DRAFT`. Publication sets `status` to `PUBLISHED` with `published_at` stamped, moves every other rule set standing in `PUBLISHED` to `SUPERSEDED` — normally exactly one — and cascades identically to a universe publication: every processing run still pinned to a superseded rule set and standing in `OPEN`, `EDITED` or `WEIGHTED` is forced to `PENDING_REPIN` with `repin_required_reason` `RULE_SET_SUPERSEDED`, and every non-terminal client deliverable of those runs is moved to `HELD` with `hold_reason` `UPSTREAM_RUN_REPIN`. A run already sitting in `PENDING_REPIN` is left alone and keeps the reason it already carries; a superseded rule set's `published_at` is left as it stands, since a rule set records no supersession timestamp of its own.

There is a second, governed route into `PUBLISHED`: a methodology change activation publishes the draft rule set it proposes and supersedes the rule set it targets, described in §3.9. Both routes reach the same states; the difference is that the direct route is a statistician's unilateral act while the governed route carries client notification, acknowledgement and segregation-of-duties requirements. `SUPERSEDED` is terminal for a rule set — a superseded rule set is never republished, and a run that needs it must be re-pinned to a live one.

### 3.6. Tuning Interval Ingest and the Editing Pass

**Ingest.** A `MethodologyStatistician` ingests one **TuningInterval** — a single block of measured viewing from one device — by supplying the `meter_id`, the `household_id`, the `source_methodology`, a `start_iso` and `end_iso` bounding the block, a `station_code` of 1 to 24 characters and the `tuning_minutes` actually tuned. Of those inputs only `household_id` is optional: the record's stored `household_id` is always copied from the referenced meter, so omitting it is accepted and supplying it merely asserts a value that must agree with the meter's own. Two shape rules bind the payload before any business check: the submitted `household_id` must equal the meter's own `household_id`, and `tuning_minutes` must be at least 0 and must not exceed the wall length of the submitted block — the elapsed time from `start_iso` to `end_iso` divided by 60 seconds and floored to whole minutes. Either violation is refused with `ERR_INVALID_REQUEST`, the household-consistency rule being evaluated once the referenced meter has resolved. The wall-length half of that pair has no meaning when `start_iso` is not strictly before `end_iso`, so on such a payload it is not evaluated at all and the caller sees the `ERR_INVALID_WINDOW` of business check 1 rather than an `ERR_INVALID_REQUEST`. A device cannot report more tuning than the block physically contains; note that this physical bound is entirely independent of the rule set's `invalid_tuning_max_minutes`, which is a methodological ceiling the edit pass applies later. Five business checks then run in this order:

1. `start_iso` must be strictly before `end_iso`, otherwise `ERR_INVALID_WINDOW`.
2. The referenced meter's `install_status` must be `INSTALLED`, otherwise `ERR_METER_NOT_INSTALLED`. Shipped and removed devices produce no data.
3. `source_methodology` must match the meter's `meter_type` under a fixed mapping — `TV_TUNER` collects `INHOME_TUNER`, `STREAMING_ROUTER` collects `STREAMING_SDK`, and `PORTABLE_OOH` collects `PORTABLE_OOH` — otherwise `ERR_METHODOLOGY_METER_MISMATCH`.
4. The new block, treated as half-open — `start_iso` inclusive, `end_iso` exclusive — must not overlap any existing interval of the **same meter** whose `state` is `RAW`, `EDITED` or `ASCRIBED`, otherwise `ERR_INTERVAL_OVERLAP`. Touching endpoints do not overlap: a block starting exactly where the previous one ended is accepted. An `INVALIDATED` record does not block re-ingest, which is how a corrected record replaces one the edit pass threw out.
5. `end_iso` must be at or before the current logical clock, otherwise `ERR_INTERVAL_IN_FUTURE`. The panel cannot report viewing that has not happened yet.

An ingested record starts at `state` `RAW` with `usable_minutes` 0, `ascribed` false, and `processing_run_id` and `invalidation_reason` both null. Ingest also refreshes the owning household's `compliance_rate_rolling_30`.

**The rolling compliance rate.** A household's `compliance_rate_rolling_30` is a panel-health monitor computed independently of any run. Its window is the 30 days ending at the current logical clock, inclusive of the lower bound and exclusive of the upper. The evaluated days are the count of distinct UTC calendar dates inside that window on which the household holds at least one interval in `state` `RAW`, `EDITED` or `ASCRIBED` — **reported days only**, so a household that reported on two days out of the thirty is scored out of 2 and not out of 30. A day is compliant when the household's minutes credited to that UTC calendar date reach at least 30; under this rolling variant the minutes read are the raw `tuning_minutes`, because panel-health monitoring reads what the household actually reported before any editing. An interval is credited entirely to the UTC calendar date of its `start_iso`, so a block crossing midnight counts against its start date and never splits. The rate is the compliant days divided by the evaluated days, rounded half up to 4 decimal places, and is 0.0000 when there are no evaluated days at all, which is a defined result and never a division by zero. Unedited raw data already counts toward the window, which is what lets the figure track panel health before any run has processed the data. The figure is stored, not derived at read time: it is recomputed on interval ingest and on a fault-detection scan, so a stored value is a snapshot as of the clock at the last ingest or scan and does not silently age.

**Opening a processing run.** A `MethodologyStatistician` opens a **ProcessingRun** by supplying the `market_id`, the `universe_estimate_id` and `edit_rule_set_id` the run will be pinned to, the `window_start_iso` and `window_end_iso` bounding the measurement period, and the `expected_market_version`. Seven checks run in this order:

1. The optimistic-concurrency check on `expected_market_version`, rejecting a stale read with `ERR_STALE_MARKET_VERSION`.
2. `window_start_iso` must be strictly before `window_end_iso`, otherwise `ERR_INVALID_WINDOW`.
3. The universe estimate's `market_id` must equal the run's `market_id`, otherwise `ERR_UNIVERSE_MARKET_MISMATCH`.
4. The universe estimate's `status` must be `PUBLISHED`, otherwise `ERR_UNIVERSE_NOT_PUBLISHED`. A draft universe is not a projection basis.
5. The edit rule set's `status` must be `PUBLISHED`, otherwise `ERR_RULE_SET_NOT_PUBLISHED`.
6. The run window must lie wholly inside the pinned universe vintage's effectivity range, and that range is closed at both ends: `window_start_iso` must be at or after `effective_from` and `window_end_iso` must be at or before `effective_to`, so a window ending exactly at `effective_to` is accepted rather than rejected. A violation is refused with `ERR_RUN_WINDOW_OUTSIDE_UNIVERSE`.
7. The run window must not **partially** overlap the window of any other processing run of the same market whose `state` is not `SUPERSEDED`, otherwise `ERR_RUN_WINDOW_OVERLAP`. The comparison is half-open, so a run starting exactly at another run's `window_end_iso` is accepted. A byte-identical window is the single exception to the overlap rule: it is accepted and supersedes the older run — unless that older run is `PUBLISHED`, in which case the identical window is rejected exactly like any other overlap, because published output is never quietly displaced.

An opened run starts at `state` `OPEN` with `opened_by_user_id` recording the caller, `window_minutes` computed as the elapsed time from `window_start_iso` to `window_end_iso` divided by 60 seconds, and `intab_snapshot_count` frozen at the number of `ACTIVE` households of the market at the moment of opening — a snapshot, deliberately not re-derived later, so that the panel size the run was computed against is recoverable after the panel has moved on. `contributing_household_count`, `ascribed_interval_count`, `invalidated_interval_count`, `outlier_household_count`, `excluded_cell_count` and `total_weight_mass` all start at 0; `weight_variant`, `projected_average_audience`, `published_at`, `published_by_user_id`, `repin_required_reason` and `superseded_by_run_id` all start null; and `limitation_disclosures` starts empty. `window_end_iso` must also be at or before the current logical clock — a run cannot process a period that has not finished — and a violation of that bound is reported as `ERR_INVALID_WINDOW`; it is the last check of all, evaluated after the overlap check of step 7, so a window that is simultaneously in the future and overlapping is answered with `ERR_RUN_WINDOW_OVERLAP`. Opening a run also advances the parent market's `version` by one, which is exactly why two opens against the same market cannot both quote the same `expected_market_version`.

Opening a run supersedes the past. Any earlier run of the same market standing in `OPEN`, `EDITED`, `WEIGHTED` or `PENDING_REPIN` whose `window_start_iso` and `window_end_iso` both equal the new run's moves to `SUPERSEDED`, with `superseded_by_run_id` set to the new run's identifier; that pointer is the whole record of the event on the run, which carries no `superseded_at` field of its own. That supersession releases the older run's work back to the pool: every tuning interval it had claimed returns to `state` `RAW` with `processing_run_id` null, `usable_minutes` 0 and `invalidation_reason` null, the synthetic `ASCRIBED` rows the older run created are deleted, and its household weight rows are deleted. `SUPERSEDED` is terminal. A `PUBLISHED` run is never superseded this way, because a published run still counts as non-superseded for the overlap check and an identical-window re-run against it is rejected outright.

**The editing pass.** A `MethodologyStatistician` runs the edit pass against a run whose `state` is `OPEN`, otherwise `ERR_RUN_NOT_OPEN`; the run's pinned rule set must then still be `PUBLISHED`, otherwise `ERR_RULE_SET_NOT_PUBLISHED`, the run-state check being evaluated first. The pass proceeds in seven ordered steps, and the order matters because later steps read what earlier steps wrote.

1. **Claim.** Every `RAW` interval whose household belongs to the run's market and whose block lies inside the run window — `start_iso` at or after `window_start_iso` and `end_iso` at or before `window_end_iso` — gets its `processing_run_id` set to this run. The claim order is by `household_id`, then `meter_id`, then `start_iso` ascending, then `created_at` ascending; `created_at` breaks ties and `id` never does.
2. **Invalid tuning.** A claimed record whose `tuning_minutes` exceeds the rule set's `invalid_tuning_max_minutes` moves to `state` `INVALIDATED` with `invalidation_reason` `OVER_MAX_TUNING` and `usable_minutes` 0.
3. **Credit.** Every other claimed record moves to `state` `EDITED` with `usable_minutes` set to its `tuning_minutes` multiplied by the credit factor of its `source_methodology` and rounded half up to a whole minute. The factors are fixed: `INHOME_TUNER` credits at 1.0, `STREAMING_SDK` credits at 1.0, and `PORTABLE_OOH` credits at 0.5 — out-of-home exposure is deliberately discounted by half against in-home and streaming collection, which are credited in full.
4. **Meter fault.** Every claimed record belonging to a meter whose `health_status` is `FAULTED` moves to `state` `INVALIDATED` with `invalidation_reason` `METER_FAULTED` and `usable_minutes` 0. Because this step runs after crediting, a faulted meter's records are credited and then thrown away, and the recorded reason is the fault rather than any tuning ceiling.
5. **Ascription.** For each meter, its surviving `EDITED` records are walked in `start_iso` ascending order. For each adjacent pair, the gap is the elapsed time from the earlier record's `end_iso` to the later record's `start_iso`, divided by 60 seconds and floored. When that gap is at least 1 minute and at most the rule set's `missing_interval_ascription_minutes`, exactly one synthetic record is created spanning the gap: `state` `ASCRIBED`, `ascribed` true, `start_iso` equal to the earlier record's `end_iso`, `end_iso` equal to the later record's `start_iso`, the same `meter_id`, `household_id`, `station_code` and `source_methodology` as the earlier record, `tuning_minutes` equal to the gap in minutes, `usable_minutes` equal to that gap multiplied by the credit factor of the earlier record's `source_methodology` and rounded half up to a whole minute, and `processing_run_id` set to this run. A gap of 0 minutes — two adjacent records — produces nothing, and a gap wider than the rule set's allowance is left as a hole. Meters whose `meter_type` is `PORTABLE_OOH` are never ascribed at all: out-of-home absence is real absence, not a collection gap. Synthetic records are never themselves candidates for further ascription.
6. **Outlier households.** For each household, the summed `usable_minutes` across its `EDITED` and `ASCRIBED` records claimed by this run is compared with the rule set's `outlier_household_minutes_cap`. A household strictly exceeding the cap is an outlier household, and the run's `outlier_household_count` rises by one for each: every real record of that household claimed by this run moves to `state` `INVALIDATED` with `invalidation_reason` `OUTLIER_HOUSEHOLD` and `usable_minutes` 0, while the synthetic `ASCRIBED` records the previous step created for that household are **deleted** rather than invalidated — an ascription is an inference the run has withdrawn, so it leaves no row behind and is not counted among the invalidated records. An implausibly heavy home is removed whole rather than trimmed.
7. **Tally.** The run's `invalidated_interval_count`, `ascribed_interval_count`, `outlier_household_count` and `contributing_household_count` are set from the result. `contributing_household_count` is the number of distinct households whose `status` is `ACTIVE` and which still hold at least one record of this run in `state` `EDITED` or `ASCRIBED` with `usable_minutes` above 0 — so a household that fell out of tab between ingest and the edit pass contributes data but is not counted as a contributor.

The pass moves the run's `state` from `OPEN` to `EDITED` and creates **no** household weight rows — weighting is a separate act. It appends to the run's `limitation_disclosures` in exactly this order: `OUTLIER_HOUSEHOLDS_EXCLUDED` when `outlier_household_count` is above 0, then `ASCRIBED_INTERVALS_PRESENT` when `ascribed_interval_count` is above 0. Disclosure order is part of the published record and is not sorted or de-duplicated after the fact.

### 3.7. Weighting, Projection, Publication and Re-pinning

Weighting is where a few thousand surviving households become a population projection. A `MethodologyStatistician` triggers the pass by naming a `weight_variant` of `DESIGN` or `FINAL`. Three checks run in this order:

1. The run's `state` must be `EDITED`, or it must be `WEIGHTED` with the submitted `weight_variant` **different** from the variant already applied, otherwise `ERR_RUN_NOT_EDITED`. A run in `OPEN`, `PENDING_REPIN`, `PUBLISHED` or `SUPERSEDED` cannot be weighted at all, and re-weighting with the variant already in force is refused rather than silently repeated.
2. The run's `contributing_household_count` must be at least 1, otherwise `ERR_NO_CONTRIBUTING_HOUSEHOLDS`. A window in which every interval was invalidated cannot be projected.
3. Under `weight_variant` `DESIGN` only, every contributing household's quota cell must hold at least one non-retired household so that no design denominator is zero, otherwise `ERR_DESIGN_DENOMINATOR_EMPTY`.

The pass also requires that the run's pinned universe estimate still be `PUBLISHED`, otherwise `ERR_UNIVERSE_NOT_PUBLISHED`, and that its effectivity range still cover the run window, otherwise `ERR_RUN_WINDOW_OUTSIDE_UNIVERSE`; both are evaluated after the three checks above. It imposes no further precondition. In particular the pinned editing rule set is read only for its `outlier_weight_ratio_cap` and its `status` is not re-examined at this step, and a quota cell that yields no usable denominator is quietly excluded from the projection rather than refused.

**Who gets a weight row.** One `HouseholdWeight` row is written per household holding at least one tuning interval of this run in `state` `EDITED` or `ASCRIBED` with `usable_minutes` above 0. Rows are created in household `created_at` ascending order, which is the order every subsequent tie-break in this pass depends on. Each row copies the owning run's `weight_variant`, records the household's `usable_minutes` as the sum of `usable_minutes` over that household's `EDITED` and `ASCRIBED` records of this run, and carries `base_weight`, `adjusted_weight`, `contribution`, `run_compliance_rate` and `capped`.

**The base weight.** For each row, the cell population is the `population_households` entry of the run's pinned universe estimate whose `quota_cell_id` matches the household's `quota_cell_id`. The `base_weight` is that cell population divided by a variant-specific denominator, rounded half up to 4 decimal places. The two variants differ *only* in the denominator, and the difference is the whole methodological point:

- Under `DESIGN`, the denominator is the number of households of that cell whose `status` is `RECRUITED`, `INSTALL_SCHEDULED`, `ENUM_PENDING`, `ACTIVE`, `FAULT_HOLD` or `NONCOMPLIANT_HOLD` — every non-retired recruit counts, whether or not it delivered any data. This is the design-based weight used for interim and diagnostic runs.
- Under `FINAL`, the denominator is the number of households of that cell that actually contributed at least one `EDITED` or `ASCRIBED` interval to **this** run with `usable_minutes` above 0. Only real data providers count, and that count is deliberately **not** re-filtered on the household's current `status`: a household retired after the edit pass still counts itself. The denominator can therefore never fall below the number of rows being weighted, and a zero denominator is impossible under `FINAL`. This is the published weight.

A cell is excluded from the projection — no weight row is written for any of its households — and raises the run's `excluded_cell_count` in either of two cases: its variant denominator is zero, or the run's pinned universe vintage carries no `cell_populations` entry naming it at all, which is what happens when the quota cell was created after that vintage was drafted. Only the cells of the households that would otherwise have been weighted are examined, so `excluded_cell_count` counts those cells and never every cell of the market; and since check 3 above already refuses a zero `DESIGN` denominator outright while a `FINAL` denominator can never be zero, the missing-population case is in practice the only one that fires. If every candidate cell is excluded the pass still succeeds rather than erroring: no weight row is written, `total_weight_mass` is 0.0000 and `projected_average_audience` is 0.

**Capping and redistribution.** Immediately after every `base_weight` is computed and before any contribution is computed, the run's own weight distribution is trimmed. Let the row count be the number of weight rows of this run and the mass be the sum of `base_weight` across them. The mean base is the mass divided by the row count, rounded half up to 4 decimal places, and the cap is that mean base multiplied by the rule set's `outlier_weight_ratio_cap`, again rounded to 4 decimal places. The cap is relative to this run's own mean and never to any global constant, so the same household can be capped in one run and untouched in another.

Rows whose `base_weight` is **strictly greater** than the cap are the capped rows; a row exactly at the cap is not capped. If there are no capped rows, every row's `adjusted_weight` equals its `base_weight` and the run's `total_weight_mass` is the mass. Otherwise:

1. The excess is the sum, over capped rows, of `base_weight` minus the cap.
2. Every capped row has its `adjusted_weight` set to the cap and its `capped` flag set to true.
3. The receivers are the rows whose `base_weight` is at or below the cap, ordered by `created_at` ascending. The receiver mass is the sum of `base_weight` over the receivers.
4. Each receiver's share is the excess multiplied by that receiver's `base_weight` and divided by the receiver mass, rounded half up to 4 decimal places, and its `adjusted_weight` is its `base_weight` plus that share. Redistribution is therefore proportional to size, not equal per head. In the degenerate case of a receiver mass of 0 every receiver's share is 0.0000 and no division is attempted.
5. Because each share was rounded independently, the redistributed total can drift from the original mass by a few units in the fourth decimal place. The drift is the original mass minus the sum of `adjusted_weight` across **all** rows, and it is added to the `adjusted_weight` of the **first** receiver in `created_at` ascending order. Total weight mass is conserved exactly to the last fourth-decimal unit, and `total_weight_mass` is the conserved figure.

The pass is single-pass by design: a receiver that its share pushes above the cap is **not** re-capped. Iterating to a fixed point would be a different algorithm and is not what this specification asks for.

**The projection.** With `adjusted_weight` final, the run's `projected_average_audience` is computed in three pinned steps. First, each household's `contribution` is its `adjusted_weight` multiplied by its summed usable minutes and divided by the run's `window_minutes`, rounded half up to 2 decimal places. Second, the raw total is the sum of those **already-rounded** contributions. Third, `projected_average_audience` is that raw total rounded half up to a whole household count. The rounding order is mandatory: rounding every household to 2 decimal places before summing, and only then rounding the sum, produces a different — and correct — answer from summing unrounded products and rounding once at the end. Households whose intervals were all invalidated have no weight row and contribute nothing.

Each weight row's `run_compliance_rate` is the run-scoped variant of the compliance calculation, and it differs from the household's rolling figure in three ways at once. Its window is the run window rather than the trailing 30 days. Its evaluated days are **every** calendar day of the run window — the run's `window_minutes` divided by 1440 and rounded up — whether the household reported on that day or not, so a silent day counts against the household instead of being skipped. And it reads only records in `state` `EDITED` or `ASCRIBED` whose `processing_run_id` is this run, using their credited `usable_minutes`, so records the edit pass invalidated do not count. A household can therefore show a high rolling rate and a low run-scoped rate for the same period.

**Re-weighting.** A run already `WEIGHTED` may be weighted again with the other variant. Every existing weight row of the run is deleted first, then the whole pass re-runs from the same edited data: `weight_variant`, `total_weight_mass`, `projected_average_audience` and `excluded_cell_count` are **overwritten rather than accumulated** while `intab_snapshot_count` is not rewritten at all — no weighting pass, first or second, ever touches it, and it keeps the panel size frozen at the open — and the `CELL_NO_CONTRIBUTORS` and `WEIGHT_CAP_APPLIED` disclosures are recomputed from scratch for the new variant rather than appended a second time. This is how the same window is projected under both bases without opening a second run.

The weighting pass appends to `limitation_disclosures` in exactly this order: `CELL_NO_CONTRIBUTORS` when at least one cell was excluded for a zero denominator, then `WEIGHT_CAP_APPLIED` when at least one row was capped.

**Publication.** A `MethodologyStatistician` publishes a run, and this is the most heavily gated operation in the system. Four checks run in this order:

1. The market's `recruitment_posture` must not be `FROZEN`, otherwise `ERR_MARKET_FROZEN`. An open accreditation audit stops publication.
2. The run's `state` must be `WEIGHTED`, otherwise `ERR_RUN_NOT_WEIGHTED`. There is no route to publication that skips weighting.
3. The market's `publication_blocked` must be false, otherwise `ERR_PUBLICATION_BLOCKED`. A denied accreditation outcome bars publication regardless of the run's readiness.
4. The acting `X-User-ID` must differ from the run's `opened_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`. The statistician who opened a run may not be the one who publishes it.

Publication also requires that the run's pinned universe estimate still be `PUBLISHED` — that it has not been superseded since pinning — otherwise `ERR_UNIVERSE_NOT_PUBLISHED`; that requirement is evaluated after all four checks above, so the segregation-of-duties failure surfaces first when both apply. The run's `state` becomes `PUBLISHED`, which is terminal, and `published_by_user_id` is stamped from `X-User-ID`. The market's current `limitation_disclosures` are appended to the run's own `limitation_disclosures`, so an accreditation qualification recorded before publication travels with the data forever. Finally, publication starts the commercial clock: every client deliverable already pinned to this run and standing in `SCHEDULED` becomes due, its `due_at` set to the current logical clock plus that client's `delivery_sla_hours`, walked in client `created_at` ascending order so that a premium subscriber's shorter service level is applied from its own tier and not from another's.

**Re-pinning.** A run forced to `PENDING_REPIN` by an upstream supersession is repaired by a `MethodologyStatistician` supplying a new `universe_estimate_id`, a new `edit_rule_set_id`, or both; an omitted pin is left as it was. Both inputs are genuinely optional, so a call supplying neither is accepted rather than refused: it returns the run to `OPEN` on the pins it already carries and discards the downstream artefacts below all the same. The run's `state` must be `PENDING_REPIN`, otherwise `ERR_RUN_NOT_PENDING_REPIN`. The new rule set must be `PUBLISHED`, and the new universe estimate must be `PUBLISHED` with an effectivity range that still covers the run window.

Re-pinning returns the run to `OPEN` and clears `repin_required_reason` to null, and it deliberately throws away every downstream artefact so that the new rules see untouched data: every tuning interval whose `processing_run_id` is this run returns to `state` `RAW` with `processing_run_id` null, `usable_minutes` 0 and `invalidation_reason` null; the synthetic `ASCRIBED` records the previous edit pass created are deleted outright; `invalidated_interval_count`, `ascribed_interval_count`, `outlier_household_count`, `contributing_household_count` and `excluded_cell_count` are reset to 0; `limitation_disclosures` is reset to an empty array; every household weight row of the run is deleted; and `total_weight_mass` returns to 0 with `projected_average_audience` and `weight_variant` returning to null. The run then walks the open, edit, weight and publish cycle again from the beginning. This cycle — `OPEN` to `EDITED` to `WEIGHTED`, out to `PENDING_REPIN` and back to `OPEN` — is the only loop in the run lifecycle, and `PUBLISHED` and `SUPERSEDED` are its only terminal states.

### 3.8. Client Subscriptions and the Deliverable Lifecycle

**Clients.** A `ClientServiceRep` registers a subscribing **Client** with a `name` of 1 to 120 characters, a `tier` of `BASIC`, `STANDARD` or `PREMIUM`, and a `contract_market_ids` array of 1 to 10 unique market identifiers naming the markets the subscription covers. Those identifiers are not resolved against the markets collection at registration — the body-reference step of §2.6 covers a top-level `market_id` only — so an entry naming no existing market is accepted and simply never matches any run's market later, while an array holding no entry, more than 10 entries or a duplicate entry is refused with `ERR_INVALID_REQUEST`. The tier is the only commercial input; the three derived commercial fields come from a fixed tier table and any values supplied for them in the body are ignored:

- `BASIC` sets `tier_base_fee_cents` to 25000, `delivery_sla_hours` to 168 and `custom_analysis_quota` to 0.
- `STANDARD` sets `tier_base_fee_cents` to 65000, `delivery_sla_hours` to 72 and `custom_analysis_quota` to 3.
- `PREMIUM` sets `tier_base_fee_cents` to 120000, `delivery_sla_hours` to 24 and `custom_analysis_quota` to 10.

A new client is `ACTIVE` with `custom_analysis_used`, `held_deliverable_count` and `delivery_sla_credit_cents` all 0 and `suspended_reason` null. §4 declares no operation that rewrites a client's `tier`, so a client's three derived commercial fields are in practice fixed at registration and the only client fields that move afterwards are `status`, `suspended_reason`, `custom_analysis_used`, `held_deliverable_count` and `delivery_sla_credit_cents`. Were a tier ever refreshed, all three derived fields would be recomputed from the same table, `custom_analysis_used` would still not be reset by it — that counter is never decremented by anything — only **new** deliverable rows would read the refreshed `delivery_sla_hours`, and a deliverable already carrying a `due_at` would keep the deadline its tier set at the time.

**Suspension and reinstatement.** A `ClientServiceRep` suspends a client with a required `suspended_reason` of at least 1 character and no declared upper bound. Suspension makes no state check of its own, so it is admitted whatever the client's current `status`: re-suspending an already `SUSPENDED` client is accepted and simply overwrites `suspended_reason` and re-runs the sweep. The client's `status` becomes `SUSPENDED` and every deliverable it owns standing in `SCHEDULED`, `REQUESTED`, `IN_PROGRESS` or `REVISION_REQUESTED` — walked in deliverable `created_at` ascending order — moves to `HELD` with `hold_reason` `CLIENT_REQUESTED` and `held_from_state` recording exactly where it stood; `held_deliverable_count` is then **recounted** rather than incremented, being set to the number of that client's deliverables now standing in `HELD`, so rows this sweep did not place on hold are counted in as well. Because the reason is not the reserved cascade reason, no service-level credit accrues to `delivery_sla_credit_cents` here. Reinstatement returns a client to `ACTIVE` and clears `suspended_reason`; the client's `status` must be `SUSPENDED`, otherwise `ERR_CLIENT_NOT_SUSPENDED`. Reinstatement deliberately does **not** auto-release anything: `held_deliverable_count` is left exactly as it was and each hold must be released one at a time, so a reinstated client's backlog is reviewed item by item.

**Two kinds of deliverable, created two ways.** A `ClientDeliverable` is polymorphic and its `kind` is fixed at creation; no transition ever converts one kind into the other.

A **scheduled dataset placement** puts a contractual dataset delivery on a client's schedule. A `ClientServiceRep` supplies the `processing_run_id` and a `requested_cell_count` between 0 and 24. Three checks run in this order: the client's `status` must not be `SUSPENDED`, otherwise `ERR_CLIENT_SUSPENDED`; the run's `market_id` must appear in the client's `contract_market_ids`, otherwise `ERR_MARKET_NOT_CONTRACTED` (HTTP 403, because this is a contractual entitlement failure rather than a state failure); and the run's `state` must not be `SUPERSEDED`, otherwise `ERR_RUN_SUPERSEDED`. Crucially, **any** other run state is accepted — delivery schedules are set in advance, so a placement may sit against a run that has not published and is still editable. The row is created with `kind` `SCHEDULED_DATASET`, `state` `SCHEDULED`, `question` null, `revision_count` 0, `gross_cents` 0 and `total_cents` 0; `discount_cents`, `late_penalty_cents` and `days_late` likewise start at 0, and `held_from_state`, `hold_reason`, `findings_summary` and `delivered_at` all start null. Its `due_at` is set immediately to the logical clock plus the client's `delivery_sla_hours` when the pinned run is already `PUBLISHED`, and is otherwise left null until that run publishes. Because such a row can sit against an editable run, it is precisely the row an upstream re-pin can put on hold. Placing one writes no field of the client and no field of the run, so neither parent's `version` moves — unlike filing a custom analysis, which raises `custom_analysis_used` and so advances the client's `version` by one.

A **custom analysis** is a bespoke question against data already published. A `ClientServiceRep` supplies the `client_id`, the `processing_run_id` — of the two body references the run is resolved first, so a payload naming neither an existing client nor an existing run is answered with `ERR_PROCESSING_RUN_NOT_FOUND` — a `question` of 1 to 400 characters and a `requested_cell_count` which must be at least 1 for this kind and, as for a scheduled placement, at most 24. Four checks run in this order: the client must not be `SUSPENDED` (`ERR_CLIENT_SUSPENDED`); the run's market must be contracted (`ERR_MARKET_NOT_CONTRACTED`); the run's `state` must be `PUBLISHED`, otherwise `ERR_RUN_NOT_PUBLISHED`; and the client's `custom_analysis_used` must be strictly below its `custom_analysis_quota`, otherwise `ERR_CUSTOM_ANALYSIS_QUOTA_EXCEEDED`. A `BASIC` client has a quota of 0 and can therefore never file one. The row is created with `kind` `CUSTOM_ANALYSIS` and `state` `REQUESTED` — not the machine's declared initial state — its `due_at` set to the logical clock plus the client's `delivery_sla_hours` whatever the moment of publication was, and the client's `custom_analysis_used` raised by one. Its money, hold and narrative fields start exactly as a scheduled placement's do: `revision_count`, `gross_cents`, `discount_cents`, `late_penalty_cents`, `total_cents` and `days_late` at 0, and `held_from_state`, `hold_reason`, `findings_summary` and `delivered_at` null. That counter is never given back, not by a revision, not by a hold and not by a tier change.

**The forked lifecycle.** A deliverable's `state` is one of `SCHEDULED`, `REQUESTED`, `IN_PROGRESS`, `DELIVERED`, `REVISION_REQUESTED` and `HELD`, and the two kinds walk deliberately different paths to the same terminal `DELIVERED`.

Branch A is dispatch. A `ClientServiceRep` dispatches a scheduled dataset straight from `SCHEDULED` to `DELIVERED`, skipping the analyst step entirely. Three checks run in this order: the client must not be `SUSPENDED` (`ERR_CLIENT_SUSPENDED`), the pinned run's `state` must be `PUBLISHED` (`ERR_RUN_NOT_PUBLISHED`), and the row's `state` must be `SCHEDULED` with `kind` `SCHEDULED_DATASET`, otherwise `ERR_DELIVERABLE_NOT_DELIVERABLE` — so dispatching a `HELD` placement of a suspended client reports the suspension rather than the state. The billing calculation runs, `delivered_at` is stamped from the clock, and `findings_summary` stays null — a dispatched dataset never carries an analyst narrative.

Branch B is the analyst path. A `ClientServiceRep` starts a custom analysis, moving it from `REQUESTED` or `REVISION_REQUESTED` to `IN_PROGRESS`; the client must be `ACTIVE` and the row's state and `kind` must admit the step, otherwise `ERR_DELIVERABLE_NOT_DELIVERABLE`. The rep then delivers it from `IN_PROGRESS` by supplying a mandatory `findings_summary` of at least 1 character with no declared upper bound, which is stored on the row; its shape is validated first, then the client must not be suspended (`ERR_CLIENT_SUSPENDED`) and only then must the `state` be `IN_PROGRESS` (`ERR_DELIVERABLE_NOT_DELIVERABLE`). Delivery itself re-checks no `kind`, which costs nothing because only a custom analysis can ever reach `IN_PROGRESS`. Both branches price through the same billing calculation and both carry the per-cell surcharge; what differs is that branch A never passes through `IN_PROGRESS` and never records a narrative, while branch B always does both.

**Billing.** Delivery prices the item in seven steps, all in whole cents with round half up. The single most important structural fact is that **both** bracket lookups are keyed on the gross figure — the pre-discount, pre-penalty amount — which pins the evaluation order and removes the apparent circularity between discount and penalty:

1. `gross_cents` is the client's `tier_base_fee_cents` plus `requested_cell_count` multiplied by the per-cell surcharge of 5000 cents.
2. The volume discount rate is 0.00 when `gross_cents` is below 80000, 0.10 when it is at least 80000 but below 150000, and 0.15 when it is 150000 or more.
3. `discount_cents` is `gross_cents` multiplied by that rate, rounded to a whole cent.
4. `days_late` is the elapsed time from the row's `due_at` to the current logical clock, divided by 86400 seconds, rounded **up** to a whole day and floored at 0. Because the figure is a ceiling, any lateness at all — one second past the deadline — counts as a full day late. A row whose `due_at` is still null when it prices takes `days_late` 0 and therefore no penalty; that is a reachable case, because publication stamps `due_at` only on rows standing in `SCHEDULED`, so a placement that sat `HELD` through its run's publication and was released afterwards prices against no deadline at all.
5. The penalty rate is 0.000 when `gross_cents` is below 80000, 0.015 when it is at least 80000 but below 150000, and 0.025 when it is 150000 or more. This bracket is keyed on the **gross** figure and not on the discounted net; using the net figure would land a borderline item in a lower bracket and is wrong.
6. `late_penalty_cents` is `gross_cents` multiplied by the penalty rate and by `days_late`, rounded to a whole cent.
7. `total_cents` is `gross_cents` less `discount_cents` less `late_penalty_cents`, floored at 0. A sufficiently late item is free, never negative.

The client's `tier_base_fee_cents` is read from the client row at delivery time rather than copied onto the deliverable at creation, so were a tier ever refreshed before delivery it would move the price of an undelivered item even though it would leave an existing `due_at` alone; the `requested_cell_count` the price also depends on is the deliverable's own and is never rewritten after creation. Delivery also credits the client: `delivery_sla_credit_cents` rises by the `late_penalty_cents` just computed, so the penalty the client was charged for lateness is simultaneously recorded as a service-level credit owed to it. That write is unconditional, so both delivery routes advance the client's `version` by one and refresh its `updated_at` even when the item was on time and the credit therefore moved by 0.

**Revisions.** Only a `ClientUser` may reject a delivered item, and only its own: the acting `X-User-ID` must equal the deliverable's `client_id`, otherwise `ERR_UNAUTHORIZED`, and that ownership check is evaluated before the body is validated at all, let alone before any state check. The subscriber supplies a required `reason` of at least 1 character, which is validated but not stored on the row. The row's `state` must be `DELIVERED`, its `kind` must be `CUSTOM_ANALYSIS`, and its `revision_count` must be below the limit of 2, otherwise `ERR_REVISION_LIMIT_REACHED`. The row returns to `REVISION_REQUESTED`, `revision_count` rises by one, `delivered_at` is cleared to null and `gross_cents`, `discount_cents`, `late_penalty_cents` and `total_cents` are reset to 0 — the item is unpriced until it is delivered again. `days_late` is **not** part of that reset: it keeps whatever the last pricing computed, so the record of a missed deadline survives the revision, and `due_at` is left standing as well, which is why a revised item that is re-delivered later is priced against the original deadline and can be later still. The credit already added to the client's `delivery_sla_credit_cents` by the earlier delivery is not clawed back either. The cycle `DELIVERED` to `REVISION_REQUESTED` to `IN_PROGRESS` to `DELIVERED` may therefore run at most twice. `DELIVERED` is terminal for every `SCHEDULED_DATASET` and for any custom analysis whose `revision_count` has reached 2. The servicing rep cannot open a revision on the client's behalf, and the client cannot start or deliver its own work.

**Holds and releases.** A `ClientServiceRep` puts a non-terminal deliverable on hold by supplying a `hold_reason` of `CLIENT_REQUESTED` or `DATA_QUALITY_REVIEW`. Supplying `UPSTREAM_RUN_REPIN` by hand is refused with `ERR_INVALID_REQUEST`, that reason being reserved for the system cascade; the shape check precedes the state check. The row's `state` must be `SCHEDULED`, `REQUESTED` or `IN_PROGRESS`, otherwise `ERR_DELIVERABLE_NOT_DELIVERABLE`; a `REVISION_REQUESTED` row is therefore not holdable by hand even though it is non-terminal and the reference-publication cascade of §3.5 does sweep that state, and a row already `HELD` or already `DELIVERED` is refused the same way. The hold makes no check on the client or on the pinned run, so a suspended client's row and a row of an unpublished run are both holdable. The hold records `held_from_state` as the state the row occupied immediately before the hold, sets `state` to `HELD`, and raises the client's `held_deliverable_count` by one. A service-level credit of 5 percent of the client's `tier_base_fee_cents`, rounded to a whole cent, is added to `delivery_sla_credit_cents` **only** when the `hold_reason` is `UPSTREAM_RUN_REPIN` — the platform compensates a client for its own methodology churn, not for a hold the client asked for or a quality review of its own data.

Releasing a hold restores exactly `held_from_state`, so the same call can land on `SCHEDULED`, `REQUESTED` or `IN_PROGRESS` depending on where the row was caught. The pinned run's `state` must be `PUBLISHED`, otherwise `ERR_RUN_NOT_PUBLISHED` — a run still in `PENDING_REPIN` blocks release, which is the whole point of the upstream hold — and the row's `state` must be `HELD`, otherwise `ERR_DELIVERABLE_NOT_HELD`. On release, `held_from_state` and `hold_reason` are cleared to null and the client's `held_deliverable_count` falls by one, clamped at 0 so the counter never goes negative however many times a row was recounted. Release checks nothing about the client, so a still-`SUSPENDED` client's holds may be released one row at a time without waiting for reinstatement. The credit is **not** reversed: `delivery_sla_credit_cents` only ever rises, because a service level once missed stays missed.

### 3.9. Methodology Change Governance and Accreditation Audits

The last two workflows are the governance layer. Neither produces measurement data; both constrain everyone who does.

**Drafting a methodology change.** A `GovernanceDirector` opens a **MethodologyChange** proposing that one editing rule set replace another. The payload carries a `title` of 1 to 160 characters, the `target_edit_rule_set_id` being retired, the `proposed_edit_rule_set_id` being promoted, an `affected_market_ids` array of 1 to 10 unique market identifiers, and an optional `supersedes_change_id` chaining this change to the one it replaces. The `proposed_edit_rule_set_id` must differ from the `target_edit_rule_set_id` **and** the named target must be the currently `PUBLISHED` rule set, otherwise `ERR_RULE_SET_NOT_DISTINCT`. A supplied `supersedes_change_id` must name a change standing in `DRAFT`, `IMPACT_ASSESSED` or `NOTIFIED`; a value naming an already-effective change is refused with `ERR_INVALID_REQUEST`, and that check is evaluated **before** the `ERR_RULE_SET_NOT_DISTINCT` pair above, so a draft that gets both wrong is answered with the `ERR_INVALID_REQUEST`. The `affected_market_ids` entries are not resolved against the markets collection, exactly as a client's `contract_market_ids` are not, so an identifier naming no market is accepted and simply matches no client at notification and no baseline run at assessment; an array holding no entry, more than 10 entries or a duplicate entry is refused with `ERR_INVALID_REQUEST`. The change starts in `DRAFT` with `created_by_user_id` stamped from `X-User-ID`, `impact_delta_pct` at 0.0000, `impact_tier` null and `revision_count` 0, and with `baseline_processing_run_id`, `baseline_projected_average_audience`, `notification_lead_hours`, `notification_deadline_at` and `activated_at` all null and `notified_client_count` and `acknowledged_client_count` both 0.

**The impact analysis.** A `GovernanceDirector` assesses the change by supplying a `baseline_processing_run_id` and the `expected_methodology_change_version`. Four checks run in this order:

1. The optimistic-concurrency check on `expected_methodology_change_version`, rejecting a stale read with `ERR_STALE_METHODOLOGY_CHANGE_VERSION`.
2. The baseline run's `state` must be `PUBLISHED`, otherwise `ERR_RUN_NOT_PUBLISHED`.
3. The change's `state` must be `DRAFT`, otherwise `ERR_CHANGE_NOT_DRAFT`.
4. The baseline run must be pinned to the change's target rule set and its `market_id` must be an element of `affected_market_ids`, otherwise `ERR_BASELINE_RUN_INVALID`.

The analysis also requires that the target rule set still be `PUBLISHED`, otherwise `ERR_RULE_SET_NOT_PUBLISHED`, and that the proposed rule set still be `DRAFT`, otherwise `ERR_RULE_SET_NOT_DRAFT`; both are evaluated after the four checks above and in that order, the target before the proposal. It then scores the change by comparing the two rule sets across three dimensions, reading no household or interval data at all. Each dimension yields a normalised sub-score capped at 1.0 **before** weighting, so no single dimension can carry the total past its own weight: the cap sub-score is the absolute difference between the two rule sets' `outlier_weight_ratio_cap` divided by 2.5; the tuning sub-score is the absolute difference between their `invalid_tuning_max_minutes` divided by 300; and the ascription sub-score is the absolute difference between their `missing_interval_ascription_minutes` divided by 60. `impact_delta_pct` is 0.40 times the cap sub-score plus 0.35 times the tuning sub-score plus 0.25 times the ascription sub-score, rounded half up to 4 decimal places — and that final rounding is the only one the calculation performs: the three sub-scores are carried at full precision, not themselves rounded to 4 decimal places before being weighted.

`impact_tier` follows from that figure: `MATERIAL` at 0.1500 or above, `MODERATE` at 0.0500 or above but below 0.1500, and `MINOR` below 0.0500. The tier fixes the disclosure lead time in `notification_lead_hours` — 72 hours for `MINOR`, 336 hours for `MODERATE` and 720 hours for `MATERIAL` — so a material change owes clients thirty days of warning and a minor one owes three. The analysis records `baseline_processing_run_id` and copies the baseline run's `projected_average_audience` into `baseline_projected_average_audience` for later disclosure, moves the change to `IMPACT_ASSESSED`, and advances the change's `version` by one. It does **not** touch `revision_count`: that counter belongs exclusively to the revision operation, so a draft-assess-revise-assess round trip leaves `revision_count` at exactly 1.

**Notification.** A `GovernanceDirector` fans the disclosure out to subscribers. Two checks run in this order: the change's `state` must be `IMPACT_ASSESSED`, otherwise `ERR_CHANGE_NOT_ASSESSED`; and at least one client must hold a `contract_market_ids` element that appears in the change's `affected_market_ids`, otherwise `ERR_NO_AFFECTED_CLIENTS` — a change must never become effective with nobody informed. The fan-out creates one **ClientNotification** per distinct client whose `contract_market_ids` intersect `affected_market_ids`, walked in client `created_at` ascending order. Suspended clients are notified too: disclosure is not a commercial privilege, and a client whose service is suspended for non-payment is still owed the methodological truth. Each notification starts in `state` `SENT` with `sent_at` stamped, `acknowledged_at` null, and `impact_tier` and `disclosed_delta_pct` copied from the change at that instant — a frozen copy, so a later re-analysis does not silently rewrite what a client was told. The change moves to `NOTIFIED`, `notified_client_count` is set to the number of rows created, `acknowledged_client_count` is 0, and `notification_deadline_at` is set to the current logical clock plus `notification_lead_hours`. Both counters are set from this fan-out alone, so a notification row surviving an earlier round counts toward neither — a `CANCELLED` one and an `ACKNOWLEDGED` one just as much — and a re-notified change therefore restarts at `acknowledged_client_count` 0 and must be acknowledged again row by row. A client contracted to an affected market across two rounds ends up holding one notification row per round for the same change; nothing de-duplicates them.

**Acknowledgement.** Only a `ClientUser` may acknowledge, and only its own notification: the acting `X-User-ID` must equal the notification's `client_id`, otherwise `ERR_UNAUTHORIZED`, evaluated before any state check. The notification's `state` must be `SENT`, otherwise `ERR_NOTIFICATION_NOT_SENT` — an already-acknowledged or cancelled row cannot be acknowledged again — and the owning change must still be in `NOTIFIED`, otherwise `ERR_CHANGE_NOT_NOTIFIED`. The notification moves to `ACKNOWLEDGED` with `acknowledged_at` stamped, and the change's `acknowledged_client_count` rises by one. `ACKNOWLEDGED` and `CANCELLED` are both terminal.

**Revision.** A `GovernanceDirector` sends a change back to `DRAFT` when the analysis or the disclosure was wrong, supplying a required `reason` of at least 1 character which is validated but not stored on the row. The change's `state` must be `IMPACT_ASSESSED` or `NOTIFIED`, otherwise `ERR_CHANGE_NOT_DRAFT`. The change returns to `DRAFT` and `revision_count` rises by one; `impact_delta_pct`, `impact_tier`, `notification_lead_hours`, `notification_deadline_at`, `baseline_processing_run_id` and `baseline_projected_average_audience` are all cleared to null — `impact_delta_pct` included, so a revised change carries a null delta rather than returning to the 0.0000 a freshly drafted one starts with. Every notification of this change standing in `SENT` moves to `CANCELLED`, while rows already `ACKNOWLEDGED` are left untouched — a conditional cascade, because an acknowledgement is a fact about the past and is not withdrawn. `notified_client_count` and `acknowledged_client_count` are then recomputed from the surviving rows, which is what makes the counters safe to rebuild: a cancelled notification counts toward neither. There is no bound on `revision_count`; the cycle `DRAFT` to `IMPACT_ASSESSED` to `NOTIFIED` and back to `DRAFT` may run indefinitely.

**Activation.** A `GovernanceDirector` activates the change, and this is the single most consequential cascade in the platform. Four checks run in this order:

1. The acting `X-User-ID` must differ from the change's `created_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`. The director who drafted a change may not be the one who makes it effective.
2. The change's `state` must be `NOTIFIED`, otherwise `ERR_CHANGE_NOT_NOTIFIED`.
3. `acknowledged_client_count` must equal `notified_client_count`, otherwise `ERR_ACKNOWLEDGEMENTS_MISSING`. Every notified client must have acknowledged.
4. The current logical clock must have reached `notification_deadline_at`, otherwise `ERR_NOTIFICATION_PERIOD_OPEN`. The tier's lead time must have fully elapsed even when every client acknowledged early — the waiting period protects clients who read their mail late as much as those who answer at once.

Activation also requires that the proposed rule set still be `DRAFT`, otherwise `ERR_RULE_SET_NOT_DRAFT`, evaluated after the four checks above; the target rule set's own `status` is deliberately not re-examined here, so a target already carried to `SUPERSEDED` by the direct publication route of §3.5 does not block the activation. It then runs a four-link cascade in this order:

- **Link 1**: the change's `state` becomes `EFFECTIVE` — terminal — with `activated_at` stamped; the proposed rule set's `status` becomes `PUBLISHED` with `published_at` stamped; and the target rule set's `status` becomes `SUPERSEDED`.
- **Link 2**, caused by link 1's supersession: every processing run whose `edit_rule_set_id` is the superseded target and whose `state` is `OPEN` or `EDITED` moves to `PENDING_REPIN` with `repin_required_reason` `RULE_SET_SUPERSEDED`, walked in run `created_at` ascending order. A run caught in `EDITED` additionally has every household weight row deleted, `total_weight_mass` reset to 0 and `projected_average_audience` reset to null. The sweep is keyed on the rule-set pin alone and is **not** narrowed to `affected_market_ids`, so a run of a market outside the change's declared scope that happens to be pinned to the same target rules is caught too. Every other run state is left exactly as it stands — `WEIGHTED` included, so unlike the reference-publication cascade of §3.5 this link never stalls a weighted run — and the link touches nothing on a caught run beyond `state`, `repin_required_reason` and, for an `EDITED` run, those two weighting figures: `weight_variant`, the editing counters and `limitation_disclosures` are all left as they were, and clearing them is the re-pin's job in §3.7.
- **Link 3**, caused by link 2's state change: every client deliverable of those runs standing in `SCHEDULED`, `REQUESTED` or `IN_PROGRESS` moves to `HELD` with `hold_reason` `UPSTREAM_RUN_REPIN` and `held_from_state` recorded, walked in deliverable `created_at` ascending order. Only the runs link 2 actually moved contribute deliverables, and the three states above are the whole list: a `REVISION_REQUESTED` row is **not** held by this cascade, unlike the reference-publication cascade of §3.5 which does sweep that state as well, and rows already `HELD` or already `DELIVERED` are left untouched. The link fires at all only when link 2 moved at least one run.
- **Link 4**, caused by link 3's holds: for each held row the owning client's `held_deliverable_count` rises by one and its `delivery_sla_credit_cents` rises by 5 percent of that client's `tier_base_fee_cents`, rounded half up to a whole cent.

A change named by another change's `supersedes_change_id` keeps its own `state` throughout: activation never rewrites history.

**Opening an accreditation audit.** An `AccreditationAuditor` opens an **AccreditationAudit** of a market's methodology, supplying the `market_id`, the `scope_edit_rule_set_id` whose methodology is in scope, and an `auditor_note` of 1 to 400 characters recording the scope. Two checks run in this order: the scoped rule set's `status` must be `PUBLISHED`, otherwise `ERR_RULE_SET_NOT_PUBLISHED` — and that is the only thing asked of it, since the rule set need bear no relation to the market's own runs; and the market must not already hold an audit in `state` `OPEN`, otherwise `ERR_AUDIT_ALREADY_OPEN`. A market whose earlier audits are all `FINALIZED` may be audited again as often as an auditor likes, and neither the market's `recruitment_posture` nor its `publication_blocked` flag bars the opening. The audit starts in `OPEN` with `opened_by_user_id` stamped from `X-User-ID`, `outcome`, `finalized_by_user_id` and `finalized_at` null, and `limitation_disclosures` empty. Opening it raises the market's `open_audit_count` by one, which fires the first clause of the posture calculation and drives `recruitment_posture` to `FROZEN` with `posture_changed_at` updated — overriding every cell-level consideration. From that instant the market accepts no meter shipments, no enumerations in or out of tab, and no run publications.

**Finalizing.** An `AccreditationAuditor` finalizes with an `outcome` of `ACCREDITED`, `QUALIFIED` or `DENIED` and a `limitation_disclosures` array of non-empty strings. That array is a required input whatever the outcome — an omitted array, or one supplied as JSON `null`, fails the required-input step of §2.6 with `ERR_INVALID_REQUEST` even for an `ACCREDITED` finalization, where the array may be present but empty. Three checks run in this order:

1. The acting `X-User-ID` must differ from the audit's `opened_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`. The auditor who opened an audit may not sign it off.
2. The audit's `state` must be `OPEN`, otherwise `ERR_AUDIT_NOT_OPEN`. `FINALIZED` is terminal.
3. When the `outcome` is `QUALIFIED` or `DENIED`, `limitation_disclosures` must hold at least one element, otherwise `ERR_DISCLOSURE_REQUIRED`. A qualified or denied methodology must say what is wrong with it. For an `ACCREDITED` outcome the array may be empty.

In every case the audit moves to `FINALIZED` with `outcome` stored, `limitation_disclosures` stored in payload order, and `finalized_by_user_id` and `finalized_at` stamped; the market's `accreditation_status` is set to the outcome; and the market's `open_audit_count` falls by one before the posture is re-evaluated, which releases `FROZEN` when no other audit of that market is open. The three outcomes then write **disjoint** effects on the market, and the differences are the point of the whole workflow:

- `ACCREDITED` sets `publication_blocked` to false and leaves the market's `limitation_disclosures` exactly as it was. A clean audit never erases a disclosure an earlier audit recorded.
- `QUALIFIED` sets `publication_blocked` to false and appends every element of the payload's `limitation_disclosures` onto the market's `limitation_disclosures` in payload order. Publication is allowed, but every run published afterwards carries the limitations.
- `DENIED` sets `publication_blocked` to **true** and likewise appends every payload disclosure in payload order. Publication remains blocked by `publication_blocked` even after the posture leaves `FROZEN`, so releasing the freeze does not release the market.

## 4. Endpoint Definitions

Every endpoint that creates a new resource returns HTTP 201 on success; every endpoint that modifies an existing resource, advances a state machine or reads data returns HTTP 200. All request bodies and all responses use the envelope described in §2.2. Where the Authorized Role(s) column reads "Any", all seven roles may call the endpoint. Where a Description below names query filters it names them only illustratively: every collection endpoint additionally accepts each optional equality filter §2.3 lists for its collection.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Sets the server's logical clock, which every deadline, tenure, window and lateness rule in this domain reads instead of wall-clock time | Any |
| POST | `/markets` | Registers a measurement market (DMA) | `PanelOperationsManager` |
| GET | `/markets/{market_id}` | Reads one market including its live budget, posture, accreditation and cell-count roll-ups | Any |
| GET | `/markets` | Lists markets, newest first by created_at DESC then market_code ASC | Any |
| POST | `/markets/{market_id}/budget-adjustments` | Raises or lowers the market's incentive_budget_cents by delta_cents | `PanelOperationsManager` |
| POST | `/markets/{market_id}/quota-cells` | Adds one demographic x geographic quota cell to a market | `PanelOperationsManager` |
| GET | `/quota-cells/{quota_cell_id}` | Reads one quota cell with its live in-tab count, fill rate and incentive multiplier | Any |
| GET | `/quota-cells` | Lists quota cells, optionally filtered by owning market and fill status, ordered by created_at ASC | Any |
| POST | `/universe-estimates` | Drafts a population universe vintage for a market | `MethodologyStatistician` |
| POST | `/universe-estimates/{universe_estimate_id}/publish` | Publishes a DRAFT vintage | `MethodologyStatistician` |
| GET | `/universe-estimates/{universe_estimate_id}` | Reads one universe vintage including its per-cell population array | Any |
| GET | `/universe-estimates` | Lists universe vintages, optionally filtered by market and status, ordered by created_at ASC | Any |
| POST | `/edit-rule-sets` | Drafts a data-editing rule set: the ascription window for missing intervals, the invalid-tuning ceiling, the outlier household minute cap, the outlier weight ratio cap and the meter fault threshold | `MethodologyStatistician` |
| POST | `/edit-rule-sets/{edit_rule_set_id}/publish` | Publishes a DRAFT rule set | `MethodologyStatistician` |
| GET | `/edit-rule-sets/{edit_rule_set_id}` | Reads one editing rule set | Any |
| GET | `/edit-rule-sets` | Lists editing rule sets, optionally filtered by status, ordered by created_at ASC | Any |
| POST | `/households` | Recruits a household into a quota cell | `PanelOperationsManager` |
| POST | `/households/{household_id}/enumerations` | Records a household enumeration visit: the roster head-count and the number of TV sets found | `FieldTechnician` |
| POST | `/households/{household_id}/retire` | Retires a household permanently | `PanelOperationsManager` |
| POST | `/households/{household_id}/accrue-incentive` | Accrues the cooperation incentive for one payment period | `PanelOperationsManager` |
| POST | `/households/{household_id}/reverse-accrual` | Reverses a previously accrued period, e.g | `PanelOperationsManager` |
| GET | `/households/{household_id}` | Reads one household with its live status, enumeration verdict, rolling compliance rate and incentive ledger | Any |
| GET | `/households` | Lists households, optionally filtered by market, quota cell and status, ordered by created_at ASC | Any |
| POST | `/meters` | Ships a meter to a household | `FieldTechnician` |
| POST | `/meters/{meter_id}/install-confirmations` | Marks a SHIPPED meter as physically installed | `FieldTechnician` |
| POST | `/meters/{meter_id}/fault-reports` | Records a field-detected meter fault | `FieldTechnician` |
| POST | `/meters/{meter_id}/repairs` | Clears a fault after repair: health_status FAULTED or SUSPECT returns to HEALTHY | `FieldTechnician` |
| POST | `/meters/{meter_id}/removals` | Decommissions an INSTALLED meter and takes the device back out of the field: the panel's normal equipment-swap and end-of-service operation | `FieldTechnician` |
| GET | `/meters/{meter_id}` | Reads one meter with its install status, health status and last fault scan | Any |
| GET | `/meters` | Lists meters, optionally filtered by household, install status and health status, ordered by created_at ASC | Any |
| POST | `/tuning-intervals` | Ingests one raw tuning interval from an installed meter | `MethodologyStatistician` |
| GET | `/tuning-intervals/{tuning_interval_id}` | Reads one tuning interval including its edit state, invalidation reason and credited usable_minutes | `PanelOperationsManager`, `MethodologyStatistician`, `AccreditationAuditor` |
| GET | `/tuning-intervals` | Lists tuning intervals, optionally filtered by meter, household, claiming run and edit state, ordered by start_iso ASC then created_at ASC | `PanelOperationsManager`, `MethodologyStatistician`, `AccreditationAuditor` |
| POST | `/processing-runs` | Opens a measurement processing run over a window of one market, version-pinning the PUBLISHED universe vintage and the PUBLISHED edit rule set it will use | `MethodologyStatistician` |
| POST | `/processing-runs/{processing_run_id}/detect-faults` | Runs meter_missing_minutes across every INSTALLED meter of the run's market, marking meters SUSPECT or FAULTED from the coverage shortfall inside the run window | `MethodologyStatistician` |
| POST | `/processing-runs/{processing_run_id}/edit` | Applies the pinned rule set's data-editing rules to every RAW interval inside the window: claims them for the run, invalidates over-max tuning, credits minutes by collection methodology, invalidates records from FAULTED meters, ascribes missing intervals inside the ascription window, then invalidates whole outlier households | `MethodologyStatistician` |
| POST | `/processing-runs/{processing_run_id}/weight` | Projects the edited window under the requested weighting basis: household_base_weight under weight_variant DESIGN or FINAL, then weight_cap_redistribution against this run's own mean, then projected_average_audience | `MethodologyStatistician` |
| POST | `/processing-runs/{processing_run_id}/publish` | Publishes a WEIGHTED run | `MethodologyStatistician` |
| POST | `/processing-runs/{processing_run_id}/repin` | Re-pins a PENDING_REPIN run onto the currently PUBLISHED universe vintage and/or edit rule set and returns it to OPEN so it can be re-edited | `MethodologyStatistician` |
| GET | `/processing-runs/{processing_run_id}` | Reads one processing run with its pins, editing counters, weight mass and projection | Any |
| GET | `/processing-runs` | Lists processing runs, optionally filtered by market, pinned universe vintage, pinned rule set and state, ordered by window_start_iso ASC then created_at ASC | Any |
| GET | `/household-weights/{household_weight_id}` | Reads one household weight row: its base weight, its capped/redistributed adjusted weight, its run-scoped compliance rate and its contribution to the projection | `PanelOperationsManager`, `MethodologyStatistician`, `AccreditationAuditor` |
| GET | `/household-weights` | Lists household weight rows, optionally filtered by run, household and capped flag, ordered by created_at ASC | `PanelOperationsManager`, `MethodologyStatistician`, `AccreditationAuditor` |
| POST | `/clients` | Registers a subscribing client on a tier | `ClientServiceRep` |
| POST | `/clients/{client_id}/suspend` | Suspends a client for non-payment or contract breach | `ClientServiceRep` |
| POST | `/clients/{client_id}/reinstate` | Returns a SUSPENDED client to ACTIVE | `ClientServiceRep` |
| POST | `/clients/{client_id}/scheduled-deliverables` | Puts a scheduled dataset delivery for a run on the client's delivery schedule | `ClientServiceRep` |
| GET | `/clients/{client_id}` | Reads one client with its tier-derived SLA, custom-analysis usage and hold counters | Any |
| GET | `/clients` | Lists clients, optionally filtered by tier and status, ordered by created_at ASC | Any |
| POST | `/client-deliverables` | Files a custom analysis request against a published run | `ClientServiceRep` |
| POST | `/client-deliverables/{client_deliverable_id}/start` | Moves a REQUESTED or REVISION_REQUESTED CUSTOM_ANALYSIS deliverable of an ACTIVE client to IN_PROGRESS; a SCHEDULED_DATASET placement is never started and is dispatched instead | `ClientServiceRep` |
| POST | `/client-deliverables/{client_deliverable_id}/dispatch` | Dispatches a SCHEDULED_DATASET deliverable straight from SCHEDULED to DELIVERED — scheduled datasets skip the IN_PROGRESS analyst step | `ClientServiceRep` |
| POST | `/client-deliverables/{client_deliverable_id}/deliver` | Delivers an IN_PROGRESS custom analysis and prices it | `ClientServiceRep` |
| POST | `/client-deliverables/{client_deliverable_id}/request-revision` | The subscriber rejects a DELIVERED item and asks for a revision, moving it back to REVISION_REQUESTED | `ClientUser` |
| POST | `/client-deliverables/{client_deliverable_id}/hold` | Puts a non-terminal deliverable on hold, recording the state it was held from so the release is exact | `ClientServiceRep` |
| POST | `/client-deliverables/{client_deliverable_id}/release` | Releases a HELD deliverable back to exactly the state it was held from, which is what held_from_state records — the release is a compensating move, not a reset to SCHEDULED | `ClientServiceRep` |
| GET | `/client-deliverables/{client_deliverable_id}` | Reads one deliverable with its hold provenance, revision count and billing breakdown | Any |
| GET | `/client-deliverables` | Lists deliverables, optionally filtered by client, pinned run, kind and state, ordered by created_at ASC | Any |
| POST | `/methodology-changes` | Opens a methodology change proposing a DRAFT rule set to replace the currently PUBLISHED one across a set of affected markets | `GovernanceDirector` |
| POST | `/methodology-changes/{methodology_change_id}/impact-analyses` | Runs methodology_impact_delta against a PUBLISHED baseline run, classifying the change MINOR, MODERATE or MATERIAL and deriving the client notification lead time and deadline from that tier | `GovernanceDirector` |
| POST | `/methodology-changes/{methodology_change_id}/notify` | Notifies every client contracted to an affected market, creating one ClientNotification per client with the change's impact tier and disclosed delta | `GovernanceDirector` |
| POST | `/methodology-changes/{methodology_change_id}/request-revision` | Sends an IMPACT_ASSESSED or NOTIFIED change back to DRAFT because the analysis or the disclosure was wrong | `GovernanceDirector` |
| POST | `/methodology-changes/{methodology_change_id}/activate` | Activates the change: the proposed rule set is published, the target rule set is superseded, and every non-terminal run pinned to the old rules is forced to PENDING_REPIN | `GovernanceDirector` |
| GET | `/methodology-changes/{methodology_change_id}` | Reads one methodology change with its impact analysis, notification counters and rule-set pins | Any |
| GET | `/methodology-changes` | Lists methodology changes, optionally filtered by state, by either pinned rule set and by the change they supersede, ordered by created_at ASC | Any |
| POST | `/client-notifications/{client_notification_id}/acknowledge` | The subscriber acknowledges a methodology change notification | `ClientUser` |
| GET | `/client-notifications/{client_notification_id}` | Reads one methodology change notification with its disclosed impact | Any |
| GET | `/client-notifications` | Lists notifications, optionally filtered by the change being disclosed, the notified client and acknowledgement state, ordered by created_at ASC | Any |
| POST | `/accreditation-audits` | Opens an accreditation audit of a market's methodology, scoped to a PUBLISHED rule set | `AccreditationAuditor` |
| POST | `/accreditation-audits/{accreditation_audit_id}/finalize` | Finalizes the audit with an outcome and, for QUALIFIED or DENIED outcomes, the limitations that must be disclosed with the data | `AccreditationAuditor` |
| GET | `/accreditation-audits/{accreditation_audit_id}` | Reads one accreditation audit with its outcome and disclosed limitations | Any |
| GET | `/accreditation-audits` | Lists accreditation audits, optionally filtered by market, scoped rule set and state, ordered by created_at ASC | Any |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_METHOD_NOT_ALLOWED` | 405 |
| `ERR_MARKET_NOT_FOUND` | 404 |
| `ERR_QUOTA_CELL_NOT_FOUND` | 404 |
| `ERR_UNIVERSE_ESTIMATE_NOT_FOUND` | 404 |
| `ERR_EDIT_RULE_SET_NOT_FOUND` | 404 |
| `ERR_HOUSEHOLD_NOT_FOUND` | 404 |
| `ERR_METER_NOT_FOUND` | 404 |
| `ERR_TUNING_INTERVAL_NOT_FOUND` | 404 |
| `ERR_PROCESSING_RUN_NOT_FOUND` | 404 |
| `ERR_HOUSEHOLD_WEIGHT_NOT_FOUND` | 404 |
| `ERR_CLIENT_NOT_FOUND` | 404 |
| `ERR_CLIENT_DELIVERABLE_NOT_FOUND` | 404 |
| `ERR_CLIENT_NOTIFICATION_NOT_FOUND` | 404 |
| `ERR_METHODOLOGY_CHANGE_NOT_FOUND` | 404 |
| `ERR_ACCREDITATION_AUDIT_NOT_FOUND` | 404 |
| `ERR_STALE_MARKET_VERSION` | 412 |
| `ERR_STALE_METHODOLOGY_CHANGE_VERSION` | 412 |
| `ERR_CLOCK_NOT_MONOTONIC` | 422 |
| `ERR_RECRUITMENT_CLOSED` | 409 |
| `ERR_MARKET_FROZEN` | 409 |
| `ERR_QUOTA_CELL_MARKET_MISMATCH` | 422 |
| `ERR_QUOTA_CELL_FILLED` | 409 |
| `ERR_INCENTIVE_BUDGET_EXCEEDED` | 409 |
| `ERR_QUOTA_CELL_DUPLICATE` | 409 |
| `ERR_HOUSEHOLD_NOT_ACCEPTING_METERS` | 409 |
| `ERR_HOUSEHOLD_NOT_ENUMERABLE` | 409 |
| `ERR_NO_INSTALLED_METER` | 409 |
| `ERR_METER_FAULTED` | 409 |
| `ERR_HOUSEHOLD_NOT_ACTIVE` | 409 |
| `ERR_HOUSEHOLD_ALREADY_RETIRED` | 409 |
| `ERR_INCENTIVE_PERIOD_ALREADY_ACCRUED` | 409 |
| `ERR_INCENTIVE_PERIOD_NOT_ACCRUED` | 409 |
| `ERR_METER_SERIAL_DUPLICATE` | 409 |
| `ERR_METER_TYPE_ALREADY_PRESENT` | 409 |
| `ERR_METER_NOT_SHIPPED` | 409 |
| `ERR_METER_NOT_INSTALLED` | 409 |
| `ERR_METER_ALREADY_FAULTED` | 409 |
| `ERR_METER_NOT_FAULTED` | 409 |
| `ERR_HOUSEHOLD_IN_TAB` | 409 |
| `ERR_UNIVERSE_CELL_COVERAGE` | 422 |
| `ERR_UNIVERSE_VINTAGE_DUPLICATE` | 409 |
| `ERR_UNIVERSE_NOT_DRAFT` | 409 |
| `ERR_UNIVERSE_VINTAGE_TOO_SOON` | 409 |
| `ERR_UNIVERSE_NOT_PUBLISHED` | 409 |
| `ERR_UNIVERSE_MARKET_MISMATCH` | 422 |
| `ERR_RULE_SET_NOT_DRAFT` | 409 |
| `ERR_RULE_SET_NOT_PUBLISHED` | 409 |
| `ERR_RULE_SET_NOT_DISTINCT` | 422 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_METHODOLOGY_METER_MISMATCH` | 422 |
| `ERR_INTERVAL_OVERLAP` | 409 |
| `ERR_INTERVAL_IN_FUTURE` | 422 |
| `ERR_RUN_WINDOW_OUTSIDE_UNIVERSE` | 422 |
| `ERR_RUN_WINDOW_OVERLAP` | 409 |
| `ERR_RUN_NOT_OPEN` | 409 |
| `ERR_RUN_NOT_EDITED` | 409 |
| `ERR_RUN_NOT_WEIGHTED` | 409 |
| `ERR_RUN_NOT_PENDING_REPIN` | 409 |
| `ERR_RUN_NOT_PUBLISHED` | 409 |
| `ERR_RUN_SUPERSEDED` | 409 |
| `ERR_NO_CONTRIBUTING_HOUSEHOLDS` | 409 |
| `ERR_DESIGN_DENOMINATOR_EMPTY` | 409 |
| `ERR_PUBLICATION_BLOCKED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_CLIENT_SUSPENDED` | 409 |
| `ERR_CLIENT_NOT_SUSPENDED` | 409 |
| `ERR_MARKET_NOT_CONTRACTED` | 403 |
| `ERR_CUSTOM_ANALYSIS_QUOTA_EXCEEDED` | 409 |
| `ERR_DELIVERABLE_NOT_DELIVERABLE` | 409 |
| `ERR_REVISION_LIMIT_REACHED` | 409 |
| `ERR_DELIVERABLE_NOT_HELD` | 409 |
| `ERR_CHANGE_NOT_DRAFT` | 409 |
| `ERR_BASELINE_RUN_INVALID` | 422 |
| `ERR_CHANGE_NOT_ASSESSED` | 409 |
| `ERR_CHANGE_NOT_NOTIFIED` | 409 |
| `ERR_ACKNOWLEDGEMENTS_MISSING` | 409 |
| `ERR_NOTIFICATION_PERIOD_OPEN` | 409 |
| `ERR_NOTIFICATION_NOT_SENT` | 409 |
| `ERR_NO_AFFECTED_CLIENTS` | 409 |
| `ERR_AUDIT_ALREADY_OPEN` | 409 |
| `ERR_AUDIT_NOT_OPEN` | 409 |
| `ERR_DISCLOSURE_REQUIRED` | 422 |
