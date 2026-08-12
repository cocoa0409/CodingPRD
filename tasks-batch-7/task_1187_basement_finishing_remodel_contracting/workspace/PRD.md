# Basement Finishing & Remodel Contracting API — Product Requirements Document

## 1. Introduction

Finishing a basement is the most compliance-sensitive job a residential remodeling contractor takes on. The space sits below grade, so moisture decides whether the finishes survive; egress-window and ceiling-height rules decide whether the space may legally be called habitable; and the homeowners keep living upstairs while demolition, framing, plumbing, electrical, HVAC, insulation, drywall, flooring, and paint crews rotate through their home. Around those physical realities sits a financial structure of allowance budgets and change orders, a municipal permitting and inspection track, and a warranty obligation whose cost exposure depends on how fresh moisture readings compare against the originals years after the work is done.

This document specifies the Basement Finishing & Remodel Contracting API, the platform on which that work runs. It covers the full contracting lifecycle: contractor, homeowner, and subcontractor onboarding; pre-design moisture and code-readiness assessment with a remediation loop; layout design with homeowner revision cycles; permit application with egress and ceiling compliance evaluation; allowance and change-order management against a continuously recomputed contract price; sequenced scheduling of trade phases under occupied-home constraints; daily containment, noise, and cleanup discipline enforced by a strike system; rough-in and final inspections leading to certification; and post-completion warranty claims governed by a moisture-recurrence policy. All time-dependent behavior — the strike window, permit validity, certificate expiry, warranty eligibility — is evaluated against a controllable logical clock rather than wall-clock time, so every rule in this document is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring the capacity in which they act. The system recognizes five roles: `PlatformAdmin`, `Contractor`, `Homeowner`, `Subcontractor`, and `Inspector`. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE`.

Identity binding differs by role. When `X-User-Role` is `Contractor`, `X-User-ID` is the `id` of the acting Contractor; ownership checks on any resource that references a Contractor — above all the Project, whose `contractor_id` is stamped from this identity at creation — compare that foreign-key field to `X-User-ID`. When `X-User-Role` is `Homeowner`, `X-User-ID` is the `id` of the acting Homeowner, compared against the project's `homeowner_id`. When `X-User-Role` is `Subcontractor`, `X-User-ID` is the `id` of the acting Subcontractor, compared against the `subcontractor_id` of the work phase being started or completed; when filing a daily site log, the acting subcontractor must instead be assigned to at least one non-terminal work phase of the project. A failure of any of these ownership checks is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `PlatformAdmin` or `Inspector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. All five roles may call every read endpoint in the API.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order.

The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every primary resource — Contractor, Homeowner, Subcontractor, Project, MoistureAssessment, DesignPackage, Permit, AllowanceLine, ChangeOrder, WorkPhase, Inspection, Certificate, and WarrantyClaim — carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recorded at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): begins at 1 at creation and increments by one on every mutation, available for optimistic concurrency control.

The DailySiteLog is the sole exception to this convention. As an immutable daily record, it carries only `id` and `created_at`; both `updated_at` and `version` are absent. When a workflow in §3 mutates a resource as a side effect — most Project advances and cascades increment the Project's `version` — that increment is a real mutation and refreshes `updated_at` alongside it.

### 2.5. The Logical Clock and Time-Driven Expiry

The platform never consults wall-clock time. A logical clock governs every "current date" evaluation: the freshness of site-log dates, the trailing strike window, permit validity, certificate expiry, and warranty eligibility. Before any adjustment, the logical clock reads exactly 2026-05-01T00:00:00Z. A `PlatformAdmin`-only capability sets the clock to a supplied `to_iso8601` instant and returns the new `current_utc` value.

Every clock adjustment triggers the expiry sweep. A permit still in `ISSUED` whose `issued_at` date is more than 180 days behind the new current date moves to `EXPIRED`, unless its project has already reached `COMPLETED`. A certificate still `ACTIVE` whose `warranty_end` is before the new current date moves to `EXPIRED`. Both transitions are system-driven and unconditional once their date thresholds pass.

### 2.6. Request Validation Pipeline

Every request is validated in a fixed priority order, and the first failing check produces the response — later checks are not consulted. The full order is:

1. Authentication: the `X-User-Role` and `X-User-ID` headers must be present and well-formed (`ERR_UNAUTHENTICATED`).
2. Role authorization: the declared role must be permitted on the endpoint (`ERR_FORBIDDEN_ROLE`).
3. Ownership: entity-backed callers must own or be assigned to the target — Contractors and Homeowners must own the project; a Subcontractor must be the assigned crew of the phase being acted on, or, when filing a site log, must be assigned to a non-terminal phase of the project (`ERR_NOT_RESOURCE_OWNER`).
4. Path resolution: every identifier in the URL must exist and nest correctly under its parent, validated strictly left-to-right so that the first missing or mis-nested segment decides the failure (`ERR_NOT_FOUND`).
5. Body references: identifiers inside the payload — `homeowner_id`, `subcontractor_id`, `predecessor_ids`, `work_phase_id`, `certificate_id`, and the `allowance_line_id` inside each entry of `allowance_draws` — must resolve to existing records (`ERR_REFERENCED_NOT_FOUND`).
6. Concurrency: on change-order creation, `expected_project_version` must equal the project's current `version` (`ERR_STALE_PROJECT_VERSION`; see §2.8).
7. Project state gate: the parent project's status must permit the child operation (`ERR_PROJECT_STATE_FORBIDS`; per-operation gates are enumerated in §2.7).
8. Entity state: the target entity must be in a from-state that lists the requested transition (`ERR_INVALID_STATE`).
9. Terminal guard: an entity in a terminal state — a `COMPLETED` or `CANCELLED` project, an `APPROVED` or `SUPERSEDED` package, a `CLOSED` or `EXPIRED` permit, a change order in any of its four end states, a `PASSED`, `FAILED`, or `CANCELLED` inspection, a decided claim — refuses every further mutation (`ERR_ALREADY_TERMINAL`).
10. Design-submit moisture clearance (`ERR_MOISTURE_NOT_CLEARED`).
11. Permit pinned-revision freshness (`ERR_DESIGN_REVISION_STALE`).
12. Egress rule R1 on permit submission (`ERR_EGRESS_NONCOMPLIANT`).
13. Ceiling rules R2 and R3 on permit submission (`ERR_CEILING_NONCOMPLIANT`).
14. At most one `DRAFT` moisture assessment per project (`ERR_ASSESSMENT_IN_PROGRESS`).
15. A `VERIFICATION` assessment only where a `REJECTED` one exists (`ERR_REASSESSMENT_NOT_ALLOWED`).
16. Phase-graph acyclicity with existing, non-cancelled predecessors (`ERR_PHASE_CYCLE`).
17. Zone interval overlap, including the drywall dust buffer (`ERR_ZONE_SCHEDULE_OVERLAP`).
18. Daily aggregate crew capacity (`ERR_CREW_CAPACITY_EXCEEDED`).
19. Site-log work dates must not be future-dated (`ERR_FUTURE_WORK_DATE`).
20. A FINAL inspection request requires that no permit on the project is `EXPIRED` (`ERR_PERMIT_EXPIRED`).
21. A warranty claim must fall inside the certificate's active warranty window (`ERR_WARRANTY_EXPIRED`).
22. Inspection targeting: a rough-in request needs an `IN_PROGRESS` phase; a final request needs every phase finished (`ERR_PHASES_INCOMPLETE`).
23. Completing a rough-in trade phase requires a passed rough-in inspection (`ERR_ROUGH_IN_REQUIRED`).
24. Allowance draw limits on change orders (`ERR_ALLOWANCE_OVERDRAW`).
25. Fiscal floors: positive claim and base-contract amounts, non-negative budgets, valid scope quantities (`ERR_INVALID_CLAIM_AMOUNT`).
26. Request shape — deliberately last: required fields present, types and enum members valid, dates ISO-formatted with the start not after the end (`ERR_INVALID_REQUEST`).

Where several of these checks apply to one endpoint, their relative priority is exactly the order above: authentication before path resolution; the version check before the project-state gate; the pinned-revision check before egress, and egress before ceiling; the one-draft limit before the reassessment precondition; the cycle check before zone overlap before crew capacity; permit validity before inspection targeting; the warranty window before claim amounts; draw limits before fiscal floors; and request shape after everything else.

### 2.7. Project State Gates on Child Operations

A child resource may be created under a project only while the project's own status permits it. Moisture assessments open while the project is in `INTAKE`, `ASSESSMENT`, or `DESIGN`. Design packages open in `ASSESSMENT`, `DESIGN`, or `PERMITTING`. Permits open only in `PERMITTING`. Allowance lines and change orders open in any state from `INTAKE` through `IN_PROGRESS` except `SUSPENDED` — that is, `INTAKE`, `ASSESSMENT`, `DESIGN`, `PERMITTING`, `SCHEDULING`, or `IN_PROGRESS`. Work phases open in `SCHEDULING` or `IN_PROGRESS`. Daily site logs and inspection requests open only while the build is `IN_PROGRESS`. Warranty claims open only once the project is `COMPLETED`. A creation attempted in any other project state is rejected with `ERR_PROJECT_STATE_FORBIDS`.

### 2.8. Optimistic Concurrency Control

Change-order creation is the platform's single optimistic-concurrency checkpoint, and there it is mandatory: the request body must carry `expected_project_version`, the project `version` the client last observed. If that value does not equal the project's current `version` — for example because another writer has since created a change order on the project, an act that legitimately supersedes every `PROPOSED` change order and leaves the current writer's view of the project stale — the creation is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), preventing the client from building on a project state it has not observed. No other endpoint accepts a version field.

### 2.9. Money, Measurement, and Rounding Conventions

All monetary values are integers of cents — allowance budgets, contract prices, scope-item costs, draw amounts, and claim awards alike. Every rounding in the platform is round half up, applied exactly where each calculation in §3 specifies: per change-order line item before summation, on the allowance contingency, and on warranty awards. Moisture emission is measured in pounds per 1000 square feet per 24 hours, humidity as a percentage, noise in decibels, lengths in inches, and areas in square feet. Moisture risk scores are integers. Calendar values are ISO 8601 dates; a work phase occupies the half-open interval from its start date inclusive to its end date exclusive; crew capacity and warranty elapsed time are reckoned in whole days.

## 3. Business Logic & Workflows

### 3.1. Registering the Parties and Opening a Project

Before any project exists, the platform's identity anchors are seeded. A `PlatformAdmin` registers each contracting firm by its `name` and state `license_no`, and each trade crew by its `name` and `trade` — one of `DEMOLITION`, `FRAMING`, `PLUMBING`, `ELECTRICAL`, `HVAC`, `INSULATION`, `DRYWALL`, `FLOORING`, `PAINT`, or `GENERAL`. The subcontractor directory is readable by every role. Homeowner onboarding records the client's `name`, `email`, and `phone`, and may be performed either by a `PlatformAdmin` or by the engaging `Contractor`.

A `Contractor` opens a project with a payload containing the `homeowner_id`, the property `address`, the gross `basement_sqft`, and the `base_contract_cents` — the base contract price in cents, which already carries the allowance budgets and must be greater than zero, or creation fails with `ERR_INVALID_CLAIM_AMOUNT`. The server stamps the acting contractor's identity onto the project as `contractor_id`; that value never arrives through the request body. A new project starts in `INTAKE` with `strike_count` at zero and `version` at 1; `last_resumed_at` stays null until the first resume, and `approved_design_id` stays null until the first design approval. Every project read surfaces the computed `strike_count`, `contract_price_cents`, and `price_variant` alongside the stored fields, and the project list can be filtered by `homeowner_id`, `contractor_id`, `status`, or `approved_design_id`.

From intake the project walks a fixed corridor: `INTAKE` to `ASSESSMENT` when the first moisture assessment is created; `ASSESSMENT` to `DESIGN` when an assessment is accepted; `DESIGN` to `PERMITTING` when a design package is approved; `PERMITTING` to `SCHEDULING` when a permit is issued; `SCHEDULING` to `IN_PROGRESS` when the first work phase starts; and `IN_PROGRESS` to `COMPLETED` when the final inspection passes and the certificate is issued. Each advance is system-driven by its milestone, and each increments the project's `version` by one. Two states sit off the corridor: `SUSPENDED`, the strike-driven detour covered in §3.7, and `CANCELLED`, the voluntary exit. `COMPLETED` and `CANCELLED` are terminal; a project in either refuses every further mutation with `ERR_ALREADY_TERMINAL`.

Either the owning contractor or the owning homeowner may cancel a project from any non-terminal state, optionally supplying a `reason`; a caller who does not own the project is rejected with `ERR_NOT_RESOURCE_OWNER`. Cancellation cascades downward: every work phase not yet in a terminal state moves to `CANCELLED`, and every `PROPOSED` change order moves to `WITHDRAWN` with its allowance draws released back to their lines, restoring each line's `remaining_cents`. The project's `version` increments with the cancellation.

### 3.2. Moisture and Egress Assessment: Screening, Remediation, and Verification

Before any design work, the contractor records a moisture and code-readiness assessment on the project — permitted while the project is in `INTAKE`, `ASSESSMENT`, or `DESIGN`. The payload captures the four readings that drive the risk score — `slab_moisture_lbs`, the calcium-chloride slab emission in pounds per 1000 square feet per 24 hours; `interior_rh_pct`, the interior relative humidity; `efflorescence_observed`, whether visible efflorescence appears on walls or slab; and `grading_deficit`, whether an exterior grading or drainage deficit was observed — together with two code-readiness measurements: `egress_windows_existing`, the count of existing egress-capable windows, and `ceiling_height_in`, the measured clear ceiling height in inches. The optional `assessment_kind` defaults to `SCREENING`. Two creation-time guards apply, in this order: a project may hold at most one `DRAFT` assessment at a time (`ERR_ASSESSMENT_IN_PROGRESS`), and a `VERIFICATION` assessment may be created only when a `REJECTED` assessment already exists on the project (`ERR_REASSESSMENT_NOT_ALLOWED`). The first assessment created on an `INTAKE` project advances the project to `ASSESSMENT`.

Submitting an assessment computes and persists its `moisture_risk_score` and `risk_band`, then resolves it to `ACCEPTED` or `REJECTED`. Scoring uses the variant matching the `assessment_kind`, and both variants sum the same four components. Under `SCREENING`: the slab component is 0 points when `slab_moisture_lbs` is at most 3.0, 25 points when it is greater than 3.0 and at most 5.0, and 50 points when it exceeds 5.0; the humidity component is 0 points when `interior_rh_pct` is at most 60, 15 when it is greater than 60 and at most 70, and 30 when it exceeds 70; observed efflorescence adds 20 points and a grading deficit adds 15. The score is the sum of the four components, and the band is `LOW` at a score of 24 or less, `MODERATE` from 25 through 49, and `HIGH` at 50 or more. Under `VERIFICATION` the components are the same four, but the thresholds tighten: the slab component breaks at 2.0 and 4.0 — 0 points at most 2.0, 25 points above 2.0 through 4.0, 50 points above 4.0 — and the humidity component breaks at 55 and 65 — 0 points at most 55, 15 points above 55 through 65, 30 points above 65 — while the band cutoffs drop to `LOW` at 15 or less, `MODERATE` from 16 through 39, and `HIGH` at 40 or more. Identical readings therefore score lower under screening than under verification: a slab emission of 3.0 with humidity of 60 contributes no points under `SCREENING` but 40 points under `VERIFICATION`.

The band decides the outcome, and acceptance is kind-specific: a `SCREENING` assessment is accepted in either the `LOW` or `MODERATE` band, while a `VERIFICATION` assessment is accepted only in the `LOW` band. An acceptable band resolves the assessment to `ACCEPTED`, and if the project is still in `INTAKE` or `ASSESSMENT` it advances to `DESIGN`; an unacceptable band — `HIGH` for screening, or `MODERATE` or `HIGH` for verification — resolves the assessment to `REJECTED` with the project status unchanged. Submission is possible only while the project is in `INTAKE`, `ASSESSMENT`, or `DESIGN` (otherwise `ERR_PROJECT_STATE_FORBIDS`) and only from `DRAFT` (otherwise `ERR_INVALID_STATE`); an `ACCEPTED` assessment is terminal and refuses further mutation with `ERR_ALREADY_TERMINAL`.

Rejection is not the end of the road. After remediation, the contractor reopens a `REJECTED` assessment — the only state from which reopening is allowed, with any other state rejected as `ERR_INVALID_STATE` — supplying `remediation_notes` and the four post-remediation readings, which overwrite the prior readings in place. Reopening forces the `assessment_kind` to `VERIFICATION`, because a reopened assessment exists to verify remediation, and clears the computed score and band until the next submit; `remediation_notes` itself stays null on any assessment that was never reopened. The revision loop then repeats — resubmit and score again — and only a `LOW` verification band carries the project forward. All assessments of a project remain listable by every role.

### 3.3. Layout Design and the Homeowner Revision Cycle

With moisture cleared, the contractor authors design packages, creatable while the project is in `ASSESSMENT`, `DESIGN`, or `PERMITTING`. A package carries the `layout_notes` narrative describing rooms and open areas, plus a `mechanical_relocations` array — possibly empty — whose items each name the `system` being moved (one of `HVAC`, `PLUMBING`, or `ELECTRICAL`), a `description`, and an `estimated_cents` cost. Every new package starts in `DRAFT` with `revision_number` 1.

Submitting a package by the contractor moves it to `SUBMITTED` for homeowner review. Submission is possible from `DRAFT`, and again from `REVISION_REQUESTED` after the homeowner has sent the package back; any other from-state is rejected with `ERR_INVALID_STATE`. In both cases the project must hold an `ACCEPTED` moisture assessment — without one, submission is rejected with `ERR_MOISTURE_NOT_CLEARED`. A resubmission from `REVISION_REQUESTED` increments the package's `revision_number` by one, so the revision number always counts how many times the package has traveled around the negotiation loop.

Review belongs to the owning homeowner. Approval moves the package from `SUBMITTED` to `APPROVED`, supersedes any previously `APPROVED` package of the same project (which moves to `SUPERSEDED`), and sets the project's `approved_design_id` to the newly approved package; when the project is in `DESIGN` it then advances to `PERMITTING`. Requesting revisions instead moves the package from `SUBMITTED` to `REVISION_REQUESTED` and records the homeowner's `revision_notes` on the package — a field that stays null until the first such request. Both actions require the acting homeowner to own the project (`ERR_NOT_RESOURCE_OWNER`) and require the package to be `SUBMITTED` (`ERR_INVALID_STATE`). `APPROVED` and `SUPERSEDED` are terminal for a package: any further mutation attempt is rejected with `ERR_ALREADY_TERMINAL`. Packages remain individually readable, and the permits that pinned a given package can be listed from the package itself.

### 3.4. The Permit Application: Egress and Ceiling Compliance

Once a design is approved, the contractor applies for the permit; creation is gated to the `PERMITTING` state. The application payload carries the `bedroom_count` planned for the finished basement; the `windows` array, with one entry per proposed egress window giving its `net_clear_sqft` and `sill_height_in`; the main `ceiling_height_in`; and three area figures in square feet — `finished_area_sqft` for the total finished floor area, `low_area_sqft` for floor area whose ceiling height is at least 76 inches but below 84 inches (soffits and beams), and `prohibited_area_sqft` for floor area whose ceiling is below 76 inches, which must be zero for the space to be permitted. At creation the permit pins the design it is based on: `pinned_design_id` and `pinned_design_revision` capture the identity and `revision_number` of the project's currently `APPROVED` package, and the computed `egress_compliant` and `ceiling_compliant` flags remain null until the first submit.

Submitting — from `DRAFT`, or again from `CORRECTIONS_REQUIRED` after the municipality has sent the application back — runs the compliance evaluation in a fixed order. Freshness comes first: the pinned pair must still equal the identity and revision number of the project's currently `APPROVED` package, so if the homeowner has since approved a different package or a newer revision of it, submission is rejected with `ERR_DESIGN_REVISION_STALE`. Next, egress rule R1: the count of proposed windows with `net_clear_sqft` of at least 5.7 square feet and `sill_height_in` of at most 44 inches must be at least the `bedroom_count`, and failure is rejected with `ERR_EGRESS_NONCOMPLIANT` — reported even when the ceiling rules would also fail, because R1 is always evaluated and reported before R2 and R3. Then the ceiling rules: R2 requires at least half of the finished area to be full-height, evaluated exactly as `finished_area_sqft` minus `low_area_sqft` minus `prohibited_area_sqft`, doubled, being at least `finished_area_sqft` — the doubling keeps the comparison in whole square feet — and R3 requires `prohibited_area_sqft` to be exactly zero; failure of either is rejected with `ERR_CEILING_NONCOMPLIANT`. On every submission the `egress_compliant` flag (R1 alone) and the `ceiling_compliant` flag (R2 and R3 together) are computed and persisted, and a resubmission from `CORRECTIONS_REQUIRED` additionally increments `amendment_count` — which starts at zero at permit creation — by one and recomputes both flags. Submission from any state other than `DRAFT` or `CORRECTIONS_REQUIRED` is rejected with `ERR_INVALID_STATE`.

Decision-making belongs to the `Inspector`, who records an `outcome` of `ISSUED` or `CORRECTIONS_REQUIRED` with optional `notes` on a permit in `UNDER_REVIEW` (any other state is rejected with `ERR_INVALID_STATE`). Recording `ISSUED` stamps `issued_at` from the logical clock and, when the project is in `PERMITTING`, advances it to `SCHEDULING`. Recording `CORRECTIONS_REQUIRED` returns the permit for amendment and another submission. Two system-driven exits follow: a permit still `ISSUED` expires — moving to `EXPIRED` — when the clock sweeps more than 180 days past its `issued_at` while the project has not reached `COMPLETED`; and when the project's final inspection passes, an `ISSUED` permit moves to `CLOSED`. Both `CLOSED` and `EXPIRED` are terminal. Permits of a project remain listable by every role.

### 3.5. Allowances, Change Orders, and the Running Contract Price

Allowance lines budget the homeowner's not-yet-chosen finishes. The contractor creates them in any project state from `INTAKE` through `IN_PROGRESS` except `SUSPENDED`, supplying a `name` (flooring, fixtures, and the like) and the `budgeted_cents` carried for that bucket in the base contract; a negative budget is rejected with `ERR_INVALID_CLAIM_AMOUNT`. At creation `reserved_cents` and `drawn_cents` are zero, `selected` is false, `actual_cents` is zero, and `remaining_cents` equals the budget. Two derived figures track the line thereafter: `remaining_cents` is always the budget minus the reserved, drawn, and actual amounts, and `variance_cents` is the actual plus the drawn minus the budgeted amount — meaningful only once the line is selected, and null before that. An allowance line has no status machine; its lifecycle is field-driven under the project gates of §2.7. Creating a line recomputes the project price described below.

Selection belongs to the owning homeowner, who records the selection's `actual_cents` cost — re-settable on later calls as quotes firm up. Each selection sets `selected` to true, stores `actual_cents`, recomputes `variance_cents` and `remaining_cents`, recomputes the project price, and increments the project's `version`.

Change orders move scope and money in both directions. The contractor creates one with a `scope_description`, a `kind` of `ADD` or `CREDIT`, a `scope_items` array whose entries each give a `description`, a `qty` of at least 1, and a `unit_cost_cents` of at least 0 (violations are rejected with `ERR_INVALID_CLAIM_AMOUNT`), and an `allowance_draws` array whose entries each name an `allowance_line_id` and an `amount_cents`. The request must also carry `expected_project_version`, checked per §2.8 before any business rule runs. Draw limits follow: each draw's `amount_cents` must be at least 1 and no more than the line's current `remaining_cents`; the draws in total must not exceed the items total; and a `CREDIT` order must carry an empty `allowance_draws` array — any breach is rejected with `ERR_ALLOWANCE_OVERDRAW`.

Pricing is pinned to a strict order. For each scope item, `qty` is multiplied by `unit_cost_cents` and by 1.15 — a 15 percent markup — and the result is rounded half up to whole cents per line item before any summation; the rounded lines then sum to the items total. The alternative order — summing quantities times unit costs first, then applying the markup and rounding once — is forbidden because it produces different cents: two one-unit items priced at 101 and 103 cents yield 234 cents under the pinned per-line order but 235 under sum-first. For an `ADD` order, `price_delta_cents` is the items total minus the draws total; for a `CREDIT` order it is the negated items total. The signed result persists as `price_delta_cents` on the order.

Creation ripples outward. Each draw's amount is added to its line's `reserved_cents`, lowering `remaining_cents` by the same amount. Every existing `PROPOSED` change order on the same project moves to `SUPERSEDED`, and its draws are released back to their lines. The project's `version` increments.

Decision splits three ways, always from `PROPOSED` (any other state is `ERR_INVALID_STATE`, and terminal orders refuse everything with `ERR_ALREADY_TERMINAL`). The owning homeowner approves: at approval time each draw's line must still show `remaining_cents` of at least the draw amount, otherwise the approval is rejected with `ERR_ALLOWANCE_OVERDRAW`; approval then converts each draw from reserved to drawn — subtracting the amount from `reserved_cents` and adding it to `drawn_cents`, a conversion that by itself leaves `remaining_cents` unchanged — recomputes the project price, and increments the project's `version`. The owning homeowner rejects, optionally with a `reason`: all draws are released, restoring `remaining_cents`, and the project's `version` increments. The owning contractor withdraws: same release, same increment. `APPROVED`, `REJECTED`, `WITHDRAWN`, and `SUPERSEDED` are all terminal for a change order, and a project's change orders can be listed with a `status` filter.

The project's `contract_price_cents` and `price_variant` are recomputed synchronously on every change-order creation, approval, rejection, withdrawal, and supersession, and on every allowance-line selection. The evaluation order is pinned: first per-item change-order pricing into deltas; then reserve and draw movements on the lines; then the variance of each selected line; then the contingency over unselected lines; then the final sum. `price_variant` is `FINAL` when the project has no allowance lines at all or every line is selected, and `PROVISIONAL` otherwise. The `FINAL` price is `base_contract_cents` plus the summed `price_delta_cents` of all `APPROVED` change orders plus the summed `variance_cents` of all selected lines. The `PROVISIONAL` price adds a contingency of 10 percent on each unselected line's budget-minus-drawn remainder, summed and rounded half up to whole cents — so with one unselected line budgeted at 100000 cents and no other activity, the provisional price reports the base plus 10000 cents of contingency, while selecting that line flips the variant to `FINAL` and reports the base plus the line's actual-minus-budgeted variance instead.

### 3.6. Sequencing Trade Phases in the Occupied Home

With the permit issued, the contractor decomposes the build into work phases, creatable while the project is in `SCHEDULING` or `IN_PROGRESS`. The payload names the `trade` — the same ten-value enum used for subcontractor registration — a `zone` label within the basement such as REC_ROOM, BEDROOM_1, or BATH, the planned `start_date` and `end_date` as ISO dates with the start not after the end, the `crew_count` occupying the home per day, the `subcontractor_id` of the assigned crew, and an optional `predecessor_ids` array of phase references that defaults to empty. The derived `requires_rough_in` flag is true exactly when the trade is `PLUMBING`, `ELECTRICAL`, or `HVAC`.

Three creation-time constraints apply, in this order. First, the sequencing graph: every entry in `predecessor_ids` must reference an existing, non-`CANCELLED` phase of the same project, and adding an edge from each predecessor to the new phase must keep the project's phase graph acyclic — any path leading from the new phase back to one of its predecessors through existing edges rejects the creation with `ERR_PHASE_CYCLE`. Second, zone occupancy: each phase occupies the half-open interval from its `start_date` inclusive to its `end_date` exclusive within its zone, and the new phase's interval must not intersect any non-`CANCELLED` phase's interval in the same zone — intersection meaning the first interval begins before the second ends and the second begins before the first ends, so two phases whose intervals merely touch, one ending exactly when the other begins, do not overlap; a collision is rejected with `ERR_ZONE_SCHEDULE_OVERLAP`. The dust buffer tightens this around drywall: when the existing same-zone phase is a `DRYWALL` phase, the new phase's `start_date` must fall at least two full days after that phase's `end_date`, mere adjacency being insufficient, and the buffer applies symmetrically when the existing drywall phase is scheduled after the new one. Third, the occupied-home crew cap: on every calendar date covered by the new phase's interval, the summed `crew_count` of all non-`CANCELLED` phases of the project covering that date, including the new phase, must not exceed 4 — a sum of exactly 4 is permitted — or creation is rejected with `ERR_CREW_CAPACITY_EXCEEDED`. The cap is project-wide per day, with no per-zone decomposition, and dates are whole days.

Readiness is a pure function of the graph: a phase is ready exactly when it is not `CANCELLED` and every one of its predecessors is `COMPLETED`. A phase created with an empty `predecessor_ids` starts life `READY`; one with predecessors starts `PLANNED` and is promoted to `READY` by the system when its last incomplete predecessor completes.

Starting and completing phases belongs to the assigned crew. The acting subcontractor whose `id` equals the phase's `subcontractor_id` starts a `READY` phase — any other caller is rejected with `ERR_NOT_RESOURCE_OWNER`, any other from-state with `ERR_INVALID_STATE`, and the project must be in `SCHEDULING` or `IN_PROGRESS` (`ERR_PROJECT_STATE_FORBIDS`) — moving the phase to `IN_PROGRESS`; the first phase start on a `SCHEDULING` project moves the project itself to `IN_PROGRESS`. Completion moves an `IN_PROGRESS` phase to `COMPLETED` under the same ownership rule, with one trade-specific gate: when `requires_rough_in` is true, a `PASSED` rough-in inspection tied to this phase through its `work_phase_id` must already exist, otherwise completion is rejected with `ERR_ROUGH_IN_REQUIRED`. On completion, every successor phase of the same project — one whose `predecessor_ids` contains the completed phase — whose predecessors are now all `COMPLETED` promotes from `PLANNED` to `READY`; when several successors promote together they are processed in `created_at` ascending order, never by identifier.

The contractor may cancel a phase only while it is `PLANNED` or `READY`, optionally giving a `reason`, and only for a project they own (`ERR_NOT_RESOURCE_OWNER`). Phases in `IN_PROGRESS` or `BLOCKED` are cancelled only as part of a whole-project cancellation. Successors that depended solely on a cancelled phase remain `PLANNED`, because a `CANCELLED` predecessor never reaches `COMPLETED`. Phases remain readable individually, per project (filterable by `status`), and across projects with `subcontractor_id`, `project_id`, and `status` filters for reverse crew lookup.

### 3.7. Site Discipline: Daily Logs, Strikes, Suspension, and Resume

Each working day, the subcontractor on site files the daily containment, noise, and cleanup log — allowed only while the project is `IN_PROGRESS`, and only by a subcontractor assigned to a non-terminal phase of that project (`ERR_NOT_RESOURCE_OWNER` otherwise). The payload records the `work_date` — which must not be after the current logical clock date, or filing is rejected with `ERR_FUTURE_WORK_DATE` — whether `containment_intact` held all day, the `hepa_run_hours` the scrubbers ran, the `noise_db_max` peak measured at the property line, and whether `cleanup_completed` was done. The acting subcontractor's identity is stamped onto the log as its `subcontractor_id`. Logs are immutable once filed, carrying only `id` and `created_at`; every role can list a project's logs, and all logs filed by one subcontractor across projects can be listed from the subcontractor.

A log is flagged as a `violation` when containment was not intact, or cleanup was not completed, or peak noise exceeded 65 decibels. Each filing recomputes the project's `strike_count`: the count of violation logs whose `work_date` falls inside the trailing fourteen-day window ending at the current clock date inclusive — the current date and the thirteen days before it — counting, once the project has been resumed, only logs created after the last resume timestamp. Logs are counted in `work_date` order, ties broken by `created_at` ascending, never by identifier. When a new log raises the count to 3, the strike lands: that log's `strike_applied` flag becomes true (it is false otherwise), and the project moves from `IN_PROGRESS` to `SUSPENDED`.

Suspension cascades immediately. Every work phase of the project in `IN_PROGRESS` or `READY` moves to `BLOCKED`, capturing its prior state in `pre_block_status` — a field that stays null on any phase that is not currently blocked; every outstanding `REQUESTED` inspection on the project moves to `CANCELLED`; and the project's `version` increments.

Resume belongs to the owning contractor and requires the project to be `SUSPENDED` (any other state is `ERR_INVALID_STATE`; a non-owner is `ERR_NOT_RESOURCE_OWNER`). The request supplies a `remediation_note`. Resuming sets `last_resumed_at` to the current logical clock and re-anchors the strike window, so `strike_count` recomputes to zero — logs created before the resume are excluded from the count. Every `BLOCKED` phase restores its captured `pre_block_status`, returning to `READY` or `IN_PROGRESS` as recorded, and the field is cleared. The project returns to `IN_PROGRESS`, and its `version` increments.

### 3.8. Inspections, Certification, and Project Completion

While the build is `IN_PROGRESS`, the contractor requests inspections. Two kinds exist, requested with a `type` of `ROUGH_IN` or `FINAL`, and the creation guards run in a fixed order — permit validity first, then phase targeting. A `FINAL` request is refused with `ERR_PERMIT_EXPIRED` while any permit of the project is `EXPIRED`. Then targeting: a `ROUGH_IN` request must name the `work_phase_id` of a phase of this project currently `IN_PROGRESS`, and a `FINAL` request requires every work phase of the project to be `COMPLETED` or `CANCELLED`; a breach of either rule is rejected with `ERR_PHASES_INCOMPLETE`. The `work_phase_id` field is required exactly when the `type` is `ROUGH_IN` and stays null for a `FINAL` request. A new inspection starts `REQUESTED`, and requests can be listed per project — filterable by `type` and `status` — or per phase.

The `Inspector` records the result, an `outcome` of `PASSED` or `FAILED` with optional `notes`, on a `REQUESTED` inspection (any other state is `ERR_INVALID_STATE`). Either way, the clock time is stamped into `resulted_at` and the notes persist as `result_notes`, both null until resulted. A `FAILED` result is terminal for that inspection; the contractor requests a fresh one after rework. A passing rough-in simply unblocks the trade gate of §3.6. A passing final fires the certification cascade: a Certificate is created with `issued_at` set to the current logical clock, `warranty_start` equal to the issue date, and `warranty_end` 730 days later; the project's `ISSUED` permit moves to `CLOSED`; and the project itself moves from `IN_PROGRESS` to `COMPLETED`, incrementing its `version`. A project holds at most one certificate, readable per project or individually. The certificate stays `ACTIVE` until the logical clock sweeps past its `warranty_end`, at which point it moves to `EXPIRED` and refuses further transitions.

### 3.9. Warranty Claims and the Moisture Recurrence Policy

After completion, the owning homeowner may file a warranty claim against the project's certificate, supplying the `certificate_id`, a `description` of the problem, the `claimed_cents` amount — which must be greater than zero, or filing is rejected with `ERR_INVALID_CLAIM_AMOUNT` — and two fresh readings taken at claim time, `fresh_slab_moisture_lbs` and `fresh_interior_rh_pct`. Filing is gated first by the project, which must be `COMPLETED` (`ERR_PROJECT_STATE_FORBIDS` otherwise), and then by the warranty window: the claim's creation date must be on or before the certificate's `warranty_end` and the certificate must still be `ACTIVE`, otherwise filing is rejected with `ERR_WARRANTY_EXPIRED`. A new claim starts `UNDER_REVIEW`, and a `coverage_pct` preview is already computed at filing so the homeowner sees the applicable coverage tier. Claims are listable per project — filterable by `status` — and per certificate.

Decision belongs to the owning contractor, who records an `outcome` of `APPROVED` or `DENIED` with optional `notes` on an `UNDER_REVIEW` claim (any other state is `ERR_INVALID_STATE`; a non-owner is `ERR_NOT_RESOURCE_OWNER`). Coverage is a decay over the warranty term with one policy override. Elapsed time is measured in whole days, never negative, from the certificate's `warranty_start` to the claim's creation date. The moisture baseline is the `slab_moisture_lbs` of the project's baseline `ACCEPTED` moisture assessment — where several accepted assessments exist, the most recently created one wins, decided by creation timestamp and never by identifier. `moisture_recurrence_confirmed` is true exactly when `fresh_slab_moisture_lbs` is at least the baseline plus 1.5 pounds. A confirmed recurrence is covered at 100 percent regardless of elapsed time; otherwise coverage is 100 percent within the first 365 days and 50 percent through day 730. On approval, `awarded_cents` is the claimed amount capped at 200000 cents — a two-thousand-dollar ceiling — multiplied by the coverage percentage divided by 100 and rounded half up to whole cents, and the recurrence flag, `coverage_pct`, and award are computed and persisted together. A denial simply sets `awarded_cents` to 0. The award field stays null until a claim is `APPROVED`; `APPROVED` and `DENIED` are both terminal, refusing further mutation with `ERR_ALREADY_TERMINAL`.

## 4. Endpoint Definitions

Endpoints that create a new resource — whether a stand-alone anchor such as a contractor, or a child resource added under a project — return `201 Created`. Endpoints that modify or transition an existing resource, and all read endpoints, return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/contractors` | Register a contractor firm | PlatformAdmin |
| POST | `/api/homeowners` | Onboard a homeowner client | PlatformAdmin, Contractor |
| POST | `/api/subcontractors` | Register a subcontractor | PlatformAdmin |
| GET | `/api/subcontractors/{id}` | Get a subcontractor | All roles |
| GET | `/api/subcontractors/{id}/site-logs` | List daily site logs filed by a subcontractor | All roles |
| POST | `/api/projects` | Create a project; `contractor_id` stamped from the acting contractor | Contractor |
| GET | `/api/projects` | List projects with filters and pagination | All roles |
| GET | `/api/projects/{id}` | Get a project, including computed strike count and price fields | All roles |
| POST | `/api/projects/{id}/resume` | Resume a suspended project; re-anchors the strike window and restores blocked phases | Contractor |
| POST | `/api/projects/{id}/cancel` | Cancel a non-terminal project; cascades to phases and proposed change orders | Contractor, Homeowner |
| POST | `/api/projects/{id}/moisture-assessments` | Create a moisture and code-readiness assessment (draft) | Contractor |
| GET | `/api/projects/{id}/moisture-assessments` | List assessments of a project | All roles |
| POST | `/api/moisture-assessments/{id}/submit` | Submit an assessment; computes score and band, resolving accepted or rejected | Contractor |
| POST | `/api/moisture-assessments/{id}/reopen` | Reopen a rejected assessment with post-remediation readings; kind forced to verification | Contractor |
| POST | `/api/projects/{id}/design-packages` | Create a layout design package with mechanical relocation items | Contractor |
| GET | `/api/projects/{id}/design-packages` | List design packages of a project | All roles |
| GET | `/api/design-packages/{id}` | Get a design package | All roles |
| GET | `/api/design-packages/{id}/permits` | List permits pinning this design package | All roles |
| POST | `/api/design-packages/{id}/submit` | Submit a package for homeowner review; resubmission increments the revision number | Contractor |
| POST | `/api/design-packages/{id}/approve` | Homeowner approves a submitted package, superseding any prior approval | Homeowner |
| POST | `/api/design-packages/{id}/request-revision` | Homeowner requests revisions on a submitted package | Homeowner |
| POST | `/api/projects/{id}/permits` | Create a permit application pinning the approved design identity and revision | Contractor |
| GET | `/api/projects/{id}/permits` | List permits of a project | All roles |
| POST | `/api/permits/{id}/submit` | Submit or resubmit a permit; runs egress and ceiling compliance | Contractor |
| POST | `/api/permits/{id}/record-decision` | Inspector records issued or corrections-required | Inspector |
| POST | `/api/projects/{id}/allowance-lines` | Create an allowance budget line | Contractor |
| GET | `/api/projects/{id}/allowance-lines` | List allowance lines of a project | All roles |
| POST | `/api/allowance-lines/{id}/select` | Homeowner records or revises the actual selection cost; recomputes variance and price | Homeowner |
| POST | `/api/projects/{id}/change-orders` | Create a change order under optimistic concurrency; supersedes proposed orders and reserves draws | Contractor |
| GET | `/api/projects/{id}/change-orders` | List change orders of a project | All roles |
| POST | `/api/change-orders/{id}/approve` | Homeowner approves a proposed change order; converts reserved draws to drawn | Homeowner |
| POST | `/api/change-orders/{id}/reject` | Homeowner rejects a proposed change order; releases draws | Homeowner |
| POST | `/api/change-orders/{id}/withdraw` | Contractor withdraws a proposed change order; releases draws | Contractor |
| POST | `/api/projects/{id}/work-phases` | Create a sequenced work phase; graph, zone, and crew-capacity rules enforced | Contractor |
| GET | `/api/projects/{id}/work-phases` | List phases of a project | All roles |
| GET | `/api/work-phases/{id}` | Get a work phase | All roles |
| GET | `/api/work-phases` | List phases across projects, including reverse lookup by subcontractor | All roles |
| POST | `/api/work-phases/{id}/start` | Assigned subcontractor starts a ready phase | Subcontractor |
| POST | `/api/work-phases/{id}/complete` | Assigned subcontractor completes a phase; rough-in trades need a passed rough-in first | Subcontractor |
| POST | `/api/work-phases/{id}/cancel` | Contractor cancels a planned or ready phase | Contractor |
| POST | `/api/projects/{id}/site-logs` | Subcontractor files the daily containment, noise, and cleanup log | Subcontractor |
| GET | `/api/projects/{id}/site-logs` | List daily site logs of a project | All roles |
| POST | `/api/projects/{id}/inspections` | Request a rough-in (per phase) or final inspection | Contractor |
| GET | `/api/projects/{id}/inspections` | List inspections of a project | All roles |
| GET | `/api/work-phases/{id}/inspections` | List inspections tied to a phase | All roles |
| POST | `/api/inspections/{id}/record-result` | Inspector records passed or failed; a final pass issues the certificate and completes the project | Inspector |
| GET | `/api/projects/{id}/certificates` | List certificates of a project (at most one) | All roles |
| GET | `/api/certificates/{id}` | Get a certificate | All roles |
| POST | `/api/projects/{id}/warranty-claims` | Homeowner files a warranty claim with fresh moisture readings | Homeowner |
| GET | `/api/projects/{id}/warranty-claims` | List warranty claims of a project | All roles |
| GET | `/api/certificates/{id}/warranty-claims` | List claims filed against a certificate | All roles |
| POST | `/api/warranty-claims/{id}/decide` | Contractor decides approved or denied; approval computes recurrence, coverage, and award | Contractor |
| POST | `/_clock/set_current_utc` | Set the logical clock; triggers the permit and certificate expiry sweep | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCED_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_PROJECT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_PROJECT_STATE_FORBIDS` | 409 Conflict |
| `ERR_MOISTURE_NOT_CLEARED` | 409 Conflict |
| `ERR_DESIGN_REVISION_STALE` | 409 Conflict |
| `ERR_EGRESS_NONCOMPLIANT` | 422 Unprocessable Entity |
| `ERR_CEILING_NONCOMPLIANT` | 422 Unprocessable Entity |
| `ERR_ASSESSMENT_IN_PROGRESS` | 409 Conflict |
| `ERR_REASSESSMENT_NOT_ALLOWED` | 409 Conflict |
| `ERR_PHASE_CYCLE` | 422 Unprocessable Entity |
| `ERR_ZONE_SCHEDULE_OVERLAP` | 409 Conflict |
| `ERR_CREW_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_FUTURE_WORK_DATE` | 422 Unprocessable Entity |
| `ERR_PERMIT_EXPIRED` | 409 Conflict |
| `ERR_WARRANTY_EXPIRED` | 409 Conflict |
| `ERR_PHASES_INCOMPLETE` | 409 Conflict |
| `ERR_ROUGH_IN_REQUIRED` | 409 Conflict |
| `ERR_ALLOWANCE_OVERDRAW` | 422 Unprocessable Entity |
| `ERR_INVALID_CLAIM_AMOUNT` | 422 Unprocessable Entity |
