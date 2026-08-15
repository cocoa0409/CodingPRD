# BIM Coordination & Clash Detection API — Product Requirements Document

## 1. Introduction

On a large construction project every trade authors its own three-dimensional model, in its own software, at its own pace — and the building only comes together when those models do. Somebody has to federate the structural steel against the ductwork, find the places where a pipe passes through a beam, assign each clash to the trade that owns it, track the promises made in the coordination meeting, and refuse to release anything for fabrication until the right engineers have signed off. When the dust settles, somebody also has to prove to the facilities team that what was modeled is what got built. This document specifies the BIM Coordination & Clash Detection API: the system of record for that entire virtual-design-and-construction workflow.

The API governs a project from schematic design through closeout. Trade partners onboard with their authoring platforms and fiscal budgets; model revisions are submitted, audited, and superseded; federated assemblies are frozen into baselines and interrogated by clash-detection runs; clashes cycle through assignment, resolution, verification, and occasional reopening; coordination meetings convert friction into dated commitments whose breaches erode partner reliability; a coordination readiness index and posture gate every release; fabrication packages collect segregated sign-offs; and at closeout, verified as-built models and approved quantity extractions are handed to facilities for acceptance. All resources are served under the `/api` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold for every resource and every request in the system.

### 2.1. User and Role-Based Access Control

Every request must carry two identity headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an empty value in either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes six roles: `VDCManager`, `BIMCoordinator`, `TradeModelAuthor`, `LeadEngineer`, `FabricationLead`, and `FacilitiesManager`. Each mutating operation admits exactly one role, enumerated per endpoint in §4; a caller whose role is not admitted is rejected with `ERR_UNAUTHORIZED_ROLE`. All read operations (GET endpoints) are available to every one of the six roles.

Two of the roles are entity-backed. When `X-User-Role` is `TradeModelAuthor` or `FabricationLead`, `X-User-ID` is the `id` of the acting `TradePartner`; ownership checks on any resource that references a trade partner — a model's `trade_partner_id`, a clash's `assigned_trade_partner_id`, an as-built's partner, a package's `requesting_partner_id` — compare that foreign-key field to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP`. The remaining four roles are opaque: when `X-User-Role` is `VDCManager`, `BIMCoordinator`, `LeadEngineer`, or `FacilitiesManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `submitted_by_user_id` on a model, `assigned_by_user_id` on a clash, `signer_user_id` on a sign-off, or `fm_decision_by_user_id` on a handover package — but it never compares such an identifier to any entity's `id`.

The ownership check applies to exactly nine operations: creating a trade model and submitting it, resolving a clash, creating an as-built model and submitting it, and creating, submitting for sign-off, releasing, or voiding a fabrication package. For creation operations the caller's `X-User-ID` must be an existing trade partner of the project in scope, and that partner becomes the recorded owner.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order.

The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — projects, LOD requirements, trade partners, trade models, federated models and their memberships, freeze windows, clash runs, clash issues, meetings, commitments, fabrication packages, sign-offs, as-built models, quantity takeoffs, and handover packages — carries the same four system-managed fields. The `id` is a server-minted UUID used purely for identity; it carries no type prefix. The `created_at` timestamp records when the resource was created, and `updated_at` the last modification, both as ISO 8601 UTC timestamps with three fractional digits. The `version` is an integer that starts at 1 and increments by one on every mutation of that resource.

Mutation is read broadly. Any change to a resource's properties counts, including system-driven changes: a status moved by a cascade, a recomputed derived counter, a re-pinned version. Each such change refreshes `updated_at` and increments `version` on the affected resource. Recomputing a project's derived fields — its clash counters, its readiness index, its posture — is therefore itself a mutation of the project.

### 2.5. The Logical Clock

All time-dependent rules in this document — meeting windows, freeze-window activity, commitment deadlines, overdue detection — evaluate against a server-maintained **logical clock**, never against wall-clock time. Before any call has been made, the logical clock reads exactly 2026-08-01T00:00:00Z, and it must never fall back to wall-clock time.

A `VDCManager` advances the clock through the clock-setting capability, supplying a `to_iso8601` instant; the response reports the new `current_utc`. The clock moves forward only: a `to_iso8601` earlier than the current logical time is rejected with `ERR_INVALID_TIME_RANGE`. Advancing the clock recomputes the clock-dependent derived fields of every project — `overdue_commitment_count`, `coordination_readiness_index`, and `coordination_posture`. Advancing the clock does not by itself breach overdue commitments; breaching is the exclusive job of the coordination sweep described in §3.5.

### 2.6. Coordination Readiness and Project Posture

A project's coordination health is summarized by the `coordination_readiness_index` (CRI), an integer between 0 and 100. The index is recomputed on every clash import, assignment, resolution, verification, and reopening; on every commitment creation, fulfillment, breach, and waiver; on every coordination sweep; and whenever the logical clock advances. CRI starts from 100 and subtracts 25 points for each open `CRITICAL` clash in the project, 10 points for each open `MAJOR` clash, 5 points for each unassigned `MINOR` clash, and 15 points for each overdue commitment; a result below zero is floored at zero. A clash counts as open while its status is `NEW`, `ASSIGNED`, `RESOLVED`, or `REOPENED` — `VERIFIED` is closed. A `MINOR` clash counts as unassigned while `NEW` or `REOPENED`. A commitment counts as overdue while `COMMITTED` with a `due_at` strictly earlier than the logical clock. The same four counts are denormalized onto the project as `open_critical_count`, `open_major_count`, `unassigned_minor_count`, and `overdue_commitment_count`, so a project read always exposes the current breakdown.

Alongside `current_phase`, every project carries a second, parallel state dimension: `coordination_posture`. The two evolve independently — posture is never set directly and never gates phase advancement. The project sits in `COORDINATION_HOLD` whenever the CRI falls below 60, or whenever any `PROBATION` trade partner has at least one assigned clash in `ASSIGNED`, `RESOLVED`, or `REOPENED` status; otherwise it sits in `NORMAL`. The project returns to `NORMAL` once the CRI is again at least 60 and no probated partner carries an open assigned clash. While the hold is in force, both federated-model release and fabrication-package release are rejected with `ERR_PROJECT_IN_COORDINATION_HOLD`.

### 2.7. Version Pinning and Staleness Propagation

Coordination depends on knowing exactly which revision of which model every downstream artifact was built against, so the system pins versions at three points. When a federated model is assembled, each membership records the member model's `version` in `pinned_model_version`; freezing re-pins every member to its model's then-current version. When a fabrication package is created, the federated model's `version` is captured in `pinned_fed_model_version`. When a package is submitted for sign-off, each sign-off records the federated member model for its discipline as `trade_model_id` together with that model's current version as the sign-off's own `pinned_model_version`.

Pins go stale because trade models evolve. Accepting a new revision of a discipline supersedes the previously accepted one, and every federation membership that referenced the old revision is re-pointed to the new revision while keeping its previously pinned version; the containing federated model is flagged `is_stale`, and one that was `FROZEN` falls back to `ASSEMBLED`. Unfreezing — whether manual or cascade-driven — revokes every `SIGNED` sign-off issued on fabrication packages that pin that federated model, and any such package that stood at `READY_FOR_RELEASE` regresses to `SIGNOFF_IN_PROGRESS`. These reconciliations are automatic and immediate: the server transitions dependent resources as part of the triggering write, without any explicit client request on the dependent resource, and each reconciliation is a mutation under §2.4. Freezing an assembly is what clears `is_stale`, by re-pinning every member. The complete cascade rules appear where the triggering workflows are described (§3.2, §3.3, §3.6).

### 2.8. Validation Order and Hierarchical Resolution

Requests that target nested resources resolve path identifiers strictly left to right: the project first, then each nested resource in turn. The request is rejected with the not-found error of the first identifier that fails to resolve — one of `ERR_PROJECT_NOT_FOUND`, `ERR_TRADE_PARTNER_NOT_FOUND`, `ERR_TRADE_MODEL_NOT_FOUND`, `ERR_FEDERATED_MODEL_NOT_FOUND`, `ERR_CLASH_RUN_NOT_FOUND`, `ERR_CLASH_ISSUE_NOT_FOUND`, `ERR_MEETING_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`, `ERR_PACKAGE_NOT_FOUND`, `ERR_SIGNOFF_NOT_FOUND`, `ERR_AS_BUILT_NOT_FOUND`, `ERR_TAKEOFF_NOT_FOUND`, or `ERR_HANDOVER_NOT_FOUND`. Identifiers referenced in the request body — `trade_partner_id`, member model ids, `federated_model_id`, `clash_issue_id`, `committed_by_partner_id`, `trade_model_id`, `includes_takeoff_id` — must likewise resolve to existing resources, drawing the same catalogue.

Beyond existence, every request passes through twelve validation layers in a fixed order and is rejected at the first layer it fails. First, the identity headers of §2.1. Second, role authorization. Third, the ownership rule for entity-backed callers, applied to the nine operations listed there. Fourth, existence of path and body references, as above. Fifth, request shape: required fields present, types correct, enum values within range, array constraints satisfied — a fabrication scope of one to three unique disciplines, a non-empty elements array whose each `gross_qty` is at least its `deduction_qty` with neither negative, element counters non-negative with at least one element across the three criticality classes — and `ends_at` strictly after `starts_at`; shape failures are `ERR_INVALID_REQUEST`, except malformed time ranges, which are `ERR_INVALID_TIME_RANGE`. Sixth, optimistic concurrency, on the two operations that take a version field (§2.9); this check is evaluated before any business rule. Seventh, from-state legality — the target resource's current status must permit the requested transition, covering phase advancement, model submit, accept, and reject, assembly freeze, unfreeze, and release, run start and completion, clash assign, resolve, verify, and reopen, meeting start and adjourn, commitment waiver, package submit-for-signoff, release, and void, sign-off sign and decline, as-built submit and verify, takeoff approval, and handover mark-ready, transmit, and respond. Eighth, compliance and segregation gates: the LOD floor and the interoperability check at model submission, the member audit floor at freeze, the two segregation-of-duties rules at clash verification and at signing or declining a sign-off, the probation bar at clash assignment, and the posture gate at the two release operations. Ninth, same-project referential integrity: every body-referenced resource must belong to the project in the path — enforced at federated-assembly creation, clash-run creation, commitment creation, package creation, as-built creation, takeoff creation, handover creation, freeze-window creation, and clash assignment — and a commitment's `committed_by_partner_id` must equal its clash's `assigned_trade_partner_id` (`ERR_COMMITMENT_TRADE_MISMATCH`). Tenth, aggregate, uniqueness, and scoping constraints: per-project uniqueness of LOD requirements and partner company names, one member per discipline per assembly, scope-discipline membership in the assembly, the release CRI threshold, the run-completion rule, and the handover aggregate gates. Eleventh, temporal rules: room-window conflicts, meeting-window activity, freeze-window gaps and active coordination freezes, and phase timing gates. Twelfth and last, the fiscal budget check on clash resolution — a request can only fail `ERR_COORDINATION_BUDGET_EXCEEDED` after passing every earlier business rule.

### 2.9. Optimistic Concurrency Control

Two creation operations are protected by optimistic concurrency control on the parent project: assembling a federated model and extracting a quantity takeoff. Each such request must carry `expected_project_version`, set to the project `version` the client last observed. If the project's current `version` differs — because the phase was advanced, a sweep ran, or another assembly or takeoff was created since that read — the request is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412), and the client must re-read the project before retrying. The version check is evaluated before any business rule on those operations.

These two creates are guarded because each retires an existing project-scoped record as a side effect: assembling supersedes the project's current non-terminal federated model, and extracting supersedes any takeoff sharing the same key. No other endpoint accepts a version field; all other writes serialize purely through the state and business rules of §3.

### 2.10. Units, Precision, and Rounding

Distances in millimetres are compared at one decimal place: the clash-severity boundary sits at 50.0 mm and the as-built verification tolerance at 25.0 mm. Compliance scores — `submission_score` and `audit_score` — and the partner `reliability_score` are carried at one decimal place, rounded half-up. All monetary values are integer cents: `hourly_rate_cents`, `provisional_cost_cents`, and `actual_cost_cents` are whole-cent amounts, with the final multiplication rounded half-up to the nearest cent. Extracted quantities use decimal arithmetic at three decimal places, rounded half-up. The coordination readiness index, all counters, revision and run indices, and `version` fields are integers. Client-supplied timestamps (`starts_at`, `ends_at`, `due_at`) are ISO 8601 UTC and are compared at second precision.

## 3. Business Logic & Workflows

### 3.1. Project Configuration, Design Phases, and Partner Onboarding

A `VDCManager` opens a coordination engagement by creating a **Project** with a `name`. New projects begin in `SCHEMATIC_DESIGN` with `coordination_posture` at `NORMAL`, a `coordination_readiness_index` of 100, every derived counter at zero, and `ops_sweep_index` at zero.

Design proceeds through five phases in a fixed order: `SCHEMATIC_DESIGN` → `DESIGN_DEVELOPMENT` → `CONSTRUCTION_DOCUMENTS` → `CONSTRUCTION_ADMINISTRATION` → `CLOSEOUT`. A `VDCManager` advances the project's `current_phase` one step at a time along this order, and each advancement increments the project's `version` by one. `CLOSEOUT` is terminal — attempting to advance beyond it is rejected with `ERR_INVALID_PHASE_TRANSITION`. Posture, per §2.6, moves on its own track and never participates in phase advancement.

Model-authoring standards are expressed as **LOD requirements**. For each discipline — one of `ARCHITECTURAL`, `STRUCTURAL`, `MECHANICAL`, `ELECTRICAL`, `PLUMBING`, or `FIRE_PROTECTION` — a `VDCManager` registers the `min_lod` a model must declare in a given `phase`, where `min_lod` is one of 100, 200, 300, 350, 400, or 500, together with a positive `clearance_requirement_mm` that records the discipline's reference clearance tolerance for minor-clash classification. At most one requirement may exist per combination of `project_id`, `discipline`, and `phase`; a duplicate registration is rejected with `ERR_DUPLICATE_LOD_REQUIREMENT`. A project's requirements can be listed.

Trade firms join through partner onboarding. A `VDCManager` registers each **TradePartner** with a `company_name`, a `discipline` from the same six-value enumeration, a `software_platform` of `REVIT`, `TEKLA`, `ARCHICAD`, or `IFC_ONLY`, a positive integer `hourly_rate_cents` as the loaded labor rate, and a non-negative `coordination_budget_hours` as the total resolution labor the partner may consume. Company names are unique within a project — a repeated `company_name` is rejected with `ERR_DUPLICATE_TRADE_PARTNER`. A new partner starts `ACTIVE` with `reliability_score` at 100, zero `consumed_resolution_hours`, and zero `breach_count`; the reliability mechanics that move a partner to `PROBATION` when its score falls below 40 live in §3.5. The roster of a project is listable with optional `status` and `discipline` filters.

### 3.2. Trade Model Authoring, Interoperability, and the Review Cycle

Each trade authors its slice of the building as a sequence of **TradeModel** revisions. A `TradeModelAuthor` creates a revision in `DRAFT` by supplying the authoring `trade_partner_id` — which must equal the caller's `X-User-ID`, on pain of `ERR_FORBIDDEN_OWNERSHIP` — plus a `file_format` of `RVT`, `IFC`, `NWC`, or `DWG`, a `declared_lod` integer between 0 and 500, and six element counters across three criticality classes: `life_safety_elements` with `life_safety_compliant`, `envelope_elements` with `envelope_compliant`, and `finish_elements` with `finish_compliant`. Each class count must be non-negative, each compliant count must lie between zero and its class count, and the three classes must total at least one element; violations are rejected with `ERR_INVALID_REQUEST` at creation. The revision's `discipline` is copied from its authoring partner, and it receives a `revision_number` that increases monotonically per project and discipline, starting at 1.

Interoperability is judged at creation and recorded as `interop_status`, from the partner's authoring platform and the uploaded format. A model authored in `REVIT` is `NATIVE` as `RVT`, `CONVERTIBLE` as `IFC` or `NWC`, and `INCOMPATIBLE` as `DWG`. A `TEKLA` model is `NATIVE` as `IFC`, `CONVERTIBLE` as `NWC` or `DWG`, and `INCOMPATIBLE` as `RVT`. An `ARCHICAD` model is `NATIVE` as `IFC`, `CONVERTIBLE` as `DWG`, and `INCOMPATIBLE` as either `RVT` or `NWC`. An `IFC_ONLY` partner produces `NATIVE` output only as `IFC`; every other format is `INCOMPATIBLE`.

Submitting a revision moves it from `DRAFT` to `SUBMITTED` — or, in the rework loop, from `REJECTED` back to `SUBMITTED` — and any other from-state is rejected with `ERR_MODEL_NOT_SUBMITTABLE`. Ownership is enforced: the submitter's `X-User-ID` must equal the revision's `trade_partner_id`. Two compliance gates then apply. First, level of development: when a LOD requirement exists for the revision's discipline and the project's phase at submit time, `declared_lod` must be at least the required `min_lod` — equality passes — and a shortfall is rejected with `ERR_LOD_BELOW_PHASE_REQUIREMENT`; when no such requirement row exists, no LOD gate applies and submission proceeds. Second, file exchange: a revision whose `interop_status` is `INCOMPATIBLE` is rejected with `ERR_INTEROP_INCOMPATIBLE_FORMAT`. A successful submit records the caller in `submitted_by_user_id` and computes `submission_score`: one hundred times the total compliant elements divided by the total elements across all three classes, every element weighted equally, rounded half-up to one decimal place. Until its first submit, a revision's `submission_score` is null.

Review belongs to the `BIMCoordinator`, and only a `SUBMITTED` revision can be accepted or rejected — any other state draws `ERR_MODEL_NOT_SUBMITTED`. Rejection moves the revision to `REJECTED`, from which the author may resubmit after rework. Acceptance computes `audit_score`, the criticality-weighted counterpart of the submission score: life-safety elements carry weight 0.5, weather-envelope elements 0.3, and finish elements 0.2, so life safety counts two and a half times finish. For each class holding at least one element, the class's compliant ratio is multiplied by its weight; the weighted ratios are summed, divided by the sum of the included weights, multiplied by one hundred, and rounded half-up to one decimal place. Classes with zero elements are excluded and the remaining weights renormalize; since creation guarantees at least one element overall, the score is always defined. The same model data therefore generally yields a different `audit_score` than its `submission_score`, and until acceptance the `audit_score` is null.

Acceptance also drives revision supersession — a four-link cascade, plus a bubble-up, spelled out here because so much downstream state hangs on it. When the project already holds an `ACCEPTED` revision of the same discipline, that earlier revision becomes `SUPERSEDED` and the newly accepted revision's `supersedes_model_id` points back at it (link 1). Every federation membership referencing the earlier revision is re-pointed to the new one while keeping the version it had pinned; each containing federated model is flagged `is_stale`, one that was `FROZEN` falls back to `ASSEMBLED`, and assemblies in `DRAFT`, `ASSEMBLED`, or `RELEASED` keep their status (link 2). On each federated model that left `FROZEN` this way, every `SIGNED` sign-off belonging to a fabrication package that pins that federated model is revoked to `REVOKED` (link 3). Each package whose `signed_count` thereby drops below its `required_signoff_count` regresses from `READY_FOR_RELEASE` to `SIGNOFF_IN_PROGRESS` (link 4). Separately, whenever an acceptance leaves a `DRAFT` federated model whose members are now all `ACCEPTED`, that assembly advances to `ASSEMBLED` on its own. Revisions are listable with `project_id`, `trade_partner_id`, `supersedes_model_id`, `status`, and `discipline` filters — the way a supersession chain is walked.

### 3.3. Federated Assembly, Freeze Discipline, and Model Release

A `VDCManager` assembles the **FederatedModel** from member trade models, supplying a `label`, a `target_format` of `IFC` or `NWC`, and the `member_trade_model_ids`. This is one of the two operations guarded by optimistic concurrency under §2.9: the request must carry `expected_project_version`, because creating an assembly supersedes the project's current non-terminal assembly, and a writer holding a stale view of the project must re-read before writing; a mismatch is `ERR_STALE_PROJECT_VERSION`. Every member must belong to the same project as the assembly (`ERR_CROSS_PROJECT_REFERENCE`), and no two members may share a discipline (`ERR_DUPLICATE_DISCIPLINE_IN_ASSEMBLY`). Each membership is created with `pinned_model_version` set to the member model's current `version`, and the assembly receives a per-project `assembly_index` starting at 1. The new assembly starts in `ASSEMBLED` when every member model is already `ACCEPTED` at creation, and in `DRAFT` otherwise; a `DRAFT` assembly advances to `ASSEMBLED` automatically the moment all its members are accepted.

What happens to the previous assembly depends on where it stood. A superseded assembly in `DRAFT` or `ASSEMBLED` simply becomes `SUPERSEDED`. A superseded `FROZEN` assembly triggers the same revocation cascade as a manual unfreeze: `SIGNED` sign-offs on packages pinning it become `REVOKED`, and affected packages regress from `READY_FOR_RELEASE` to `SIGNOFF_IN_PROGRESS`. A superseded `RELEASED` assembly becomes `SUPERSEDED` with no revocations — the issued record is preserved. Assembly creation increments the project's `version` by one.

Freezing turns an assembly into a baseline. A `VDCManager` may freeze only from `ASSEMBLED` — otherwise `ERR_FED_NOT_ASSEMBLED` — and only when every member model's `audit_score` is at least 70.0; a member below that floor blocks the freeze with `ERR_MEMBER_COMPLIANCE_BELOW_THRESHOLD`. Freezing re-pins every member's `pinned_model_version` to that model's current version and clears `is_stale`. Unfreezing reverses the posture: from `FROZEN` — otherwise `ERR_FED_NOT_FROZEN` — the assembly returns to `ASSEMBLED`, is flagged `is_stale`, every `SIGNED` sign-off on packages pinning it is revoked, and packages whose signature count fell below requirement regress to `SIGNOFF_IN_PROGRESS`.

Issuing a frozen assembly for construction is the release. It requires the assembly to be `FROZEN` (`ERR_FED_NOT_FROZEN`), the project posture to be `NORMAL` (`ERR_PROJECT_IN_COORDINATION_HOLD`), and zero open critical clashes across the assembly's clash runs — the assembly's `open_critical_count` tracks exactly that figure, and a nonzero value blocks release with `ERR_OPEN_CLASHES_REMAIN`. The posture gate is evaluated before the open-clash gate, so a project in hold surfaces `ERR_PROJECT_IN_COORDINATION_HOLD` even when critical clashes also remain.

Freeze discipline is scheduled through **FreezeWindow** records on an assembly, each carrying a `starts_at`, an `ends_at` strictly after it (otherwise `ERR_INVALID_TIME_RANGE`), and a `purpose` of `COORDINATION_FREEZE`, `FABRICATION_HOLD`, or `HANDOVER_FREEZE`. Windows are closed intervals: a window is active at the logical clock when the clock falls on or between its two endpoints. A mandatory coordination buffer applies — relative to every existing window on the same assembly, a new window must begin at least 3,600 seconds (one hour) after the existing window ends, or end at least 3,600 seconds before the existing window begins. A gap of exactly 3,600 seconds is allowed; overlap and sub-gap adjacency alike are rejected with `ERR_FREEZE_WINDOW_GAP_VIOLATION`. This is deliberately different arithmetic from the meeting rooms of §3.5, whose intervals are half-open and may touch. Only `COORDINATION_FREEZE` windows gate clash work, as §3.4 describes. An assembly's memberships, an assembly's freeze windows, and the federation memberships of any trade model are all listable; federated models themselves are listable by `project_id` and `status`.

### 3.4. Clash Detection Runs and the Resolution Cycle

Clash detection operates against a frozen baseline. A `BIMCoordinator` opens a **ClashDetectionRun** on a `FROZEN` assembly — any other assembly state draws `ERR_FED_NOT_FROZEN` — supplying a positive `tolerance_mm` that will later arbitrate re-inspection. The run is numbered with a per-assembly `run_index` starting at 1, denormalizes its `project_id` and `federated_model_id` for scoping, counts `total_clash_count`, `open_clash_count`, and `closed_clash_count` from zero, and begins `QUEUED`.

Starting the run requires four conditions: the run still `QUEUED` (`ERR_RUN_NOT_QUEUED`), the assembly still `FROZEN` (`ERR_FED_NOT_FROZEN`), every member model `ACCEPTED` (`ERR_MODEL_NOT_ACCEPTED`), and no `COORDINATION_FREEZE` freeze window on the assembly active at the logical clock — `ERR_FREEZE_WINDOW_ACTIVE`, while windows of the other two purposes never block a start. A started run stamps `started_at` from the logical clock and becomes `RUNNING`.

While the run is `RUNNING`, the coordinator imports detected clashes; an import against a run in any other state is rejected with `ERR_RUN_NOT_RUNNING`. Each import carries an `element_pair` reference such as STR-1042/MEP-3391, a non-negative `overlap_mm` penetration depth where zero denotes a clearance-only violation, and a `spans_disciplines` flag indicating whether the two elements belong to different trade disciplines. Severity is classified at import: an overlap strictly greater than 50.0 mm is `CRITICAL`; a positive overlap of at most 50.0 mm — exactly 50.0 mm included — is `MAJOR`; an overlap of exactly 0.0 mm is `MINOR`. The new clash starts `NEW`, the run's `total_clash_count` and `open_clash_count` grow by one, and the project's CRI and posture are recomputed. Completing the run requires it `RUNNING` (`ERR_RUN_NOT_RUNNING`) with no clash still `NEW` (`ERR_RUN_HAS_UNASSIGNED_CLASHES`); completion stamps `completed_at` and lands the run in its terminal `COMPLETED` state. Runs are listable by `project_id`, `federated_model_id`, and `status`.

A clash becomes workable when the `BIMCoordinator` assigns it. Assignment is allowed from `NEW` or `REOPENED` — any other state draws `ERR_CLASH_NOT_ASSIGNABLE`. The payload's `trade_partner_id` must identify a partner in the clash's own project: an unknown identifier is `ERR_TRADE_PARTNER_NOT_FOUND`, and a partner belonging to a different project is `ERR_CROSS_PROJECT_REFERENCE`. The partner must also be `ACTIVE`; a partner on probation cannot take new clash work (`ERR_TRADE_PARTNER_ON_PROBATION`). Assignment records the partner in `assigned_trade_partner_id`, the coordinator in `assigned_by_user_id`, and computes the forward-looking `provisional_cost_cents`: a severity-based base of 40 hours for `CRITICAL`, 16 hours for `MAJOR`, or 4 hours for `MINOR`, multiplied by 1.5 when the clash spans disciplines and by 1 otherwise, multiplied by the assigned partner's current `hourly_rate_cents`, rounded half-up to whole cents. Re-assigning a `REOPENED` clash recomputes this estimate against the newly assigned partner. Every assignment recomputes the project's CRI and posture.

Resolution belongs to the trade. A `TradeModelAuthor` acting for the assigned partner — the caller's `X-User-ID` must equal the clash's `assigned_trade_partner_id`, else `ERR_FORBIDDEN_OWNERSHIP` — claims the fix from `ASSIGNED` (`ERR_CLASH_NOT_RESOLVABLE` otherwise) by reporting `actual_labor_hours`. The hours must be positive (`ERR_INVALID_REQUEST`), and the fiscal gate is always the last check of the validation order: the claimed hours must not exceed the partner's remaining coordination budget, `coordination_budget_hours` less `consumed_resolution_hours`, or the resolve is rejected with `ERR_COORDINATION_BUDGET_EXCEEDED`. A successful resolve records the caller as `resolved_by_user_id`, stores the claimed hours on the clash, moves it to `RESOLVED`, and adds the hours to the partner's `consumed_resolution_hours` — a debit that is never refunded.

Verification closes the loop and is deliberately segregated: the verifying `BIMCoordinator` must not be the operator who assigned the clash, so a caller whose `X-User-ID` equals the clash's `assigned_by_user_id` is rejected with `ERR_SOD_VERIFY_EQUALS_ASSIGN`. Verification requires `RESOLVED` (`ERR_CLASH_NOT_VERIFIABLE`) and branches on the supplied `re_inspection_overlap_mm` against the run's `tolerance_mm`. When the re-inspection overlap is at most the tolerance — equality passes — the clash becomes `VERIFIED`. Its `actual_cost_cents` is computed as the claimed `actual_labor_hours` multiplied by the partner's `hourly_rate_cents` current at verify time, rounded half-up to whole cents, with no spans multiplier; the run's `open_clash_count` decreases by one and its `closed_clash_count` increases by one, conserving the total; and the fulfillment cascade fires — a linked commitment still `COMMITTED` whose `due_at` is not earlier than the logical clock becomes `FULFILLED` with `fulfilled_at` stamped from the clock, the parent meeting's `fulfilled_commitment_count` is recomputed, and the project's CRI and posture are recomputed. When the re-inspection overlap exceeds the tolerance, the re-inspection has failed: the clash returns to `REOPENED`, its `cycle_count` increments by one, and CRI and posture are recomputed. A clash's `actual_cost_cents` stays null until its first passing verification and is overwritten by each passing verification after a reopen cycle.

Even `VERIFIED` is a resting state rather than a terminal one. A `BIMCoordinator` may reopen a verified clash — reopening from any other state is `ERR_CLASH_NOT_REOPENABLE` — which increments `cycle_count`, moves one count from `closed_clash_count` back to `open_clash_count`, and invalidates the fulfilled resolution: a linked commitment in `FULFILLED` becomes `BREACHED`, the reliability decay of §3.5 is applied to that commitment's partner with the probation consequence described there, and the project's CRI and posture are recomputed. The clash may then be re-assigned, re-resolved, and re-verified, and the cycle can repeat indefinitely. Clash issues are listable by `clash_run_id`, `federated_model_id`, `assigned_trade_partner_id`, `status`, and `severity`.

### 3.5. Coordination Meetings, Commitments, and Partner Reliability

Coordination meetings are booked per room. A `BIMCoordinator` schedules a **CoordinationMeeting** with a `room_id`, a `starts_at`, and an `ends_at` strictly after the start (otherwise `ERR_INVALID_TIME_RANGE`). Meeting intervals are half-open: the room is occupied from the start instant up to but not including the end instant. A new booking conflicts with an existing `SCHEDULED` or `IN_SESSION` meeting on the same `project_id` and `room_id` when the new meeting starts before the existing one ends and the existing one starts before the new one ends; the conflict is rejected with `ERR_ROOM_WINDOW_CONFLICT`. Adjacency is explicitly not a conflict — a meeting may begin at the exact instant another ends — and an `ADJOURNED` meeting frees its room.

Starting a meeting requires `SCHEDULED` (`ERR_MEETING_NOT_SCHEDULED`) and a logical clock inside the booked window — on or after `starts_at` and strictly before `ends_at`, else `ERR_MEETING_WINDOW_NOT_ACTIVE`; the meeting becomes `IN_SESSION`. Adjourning requires `IN_SESSION` (`ERR_MEETING_NOT_IN_SESSION`) and lands the meeting in its terminal `ADJOURNED` state.

While a meeting is `IN_SESSION` — commitments recorded at any other time fail with `ERR_MEETING_NOT_IN_SESSION` — the coordinator records **ResolutionCommitment** promises: the `clash_issue_id` being resolved, which must currently be `ASSIGNED`; the `committed_by_partner_id`, which must equal that clash's `assigned_trade_partner_id` or the record is rejected with `ERR_COMMITMENT_TRADE_MISMATCH`; and a `due_at` deadline. Both referenced resources must belong to the meeting's project (`ERR_CROSS_PROJECT_REFERENCE`). A new commitment starts `COMMITTED`, adds one to the meeting's `commitment_count`, and triggers a recompute of the project's CRI and posture.

Commitments resolve in three ways. The happy path is the verification cascade of §3.4: when the linked clash passes re-inspection while the commitment is `COMMITTED` and its `due_at` has not yet passed at the logical clock, the commitment becomes `FULFILLED` with `fulfilled_at` stamped. A `BIMCoordinator` may instead waive a `COMMITTED` commitment — waiving from any other state is `ERR_COMMITMENT_NOT_OPEN` — moving it to `WAIVED` and recomputing the project's overdue count and CRI. The unhappy path is the breach, arriving two ways: through the coordination sweep below, or through the reopen cascade of §3.4, which turns a `FULFILLED` commitment back into `BREACHED` when its clash's resolution is invalidated. `FULFILLED` is therefore not a terminal state; `BREACHED` and `WAIVED` are.

The **coordination sweep** is the `VDCManager`'s enforcement of deadlines. Invoking it walks every commitment still `COMMITTED` whose `due_at` is strictly before the logical clock — processed in creation order, earlier `created_at` first, ties broken by earlier `due_at` — and marks each one `BREACHED`. Every breach applies the reliability decay to the breaching partner and recomputes the meeting's `breached_commitment_count`; the sweep then recomputes the project's CRI and posture, increments `ops_sweep_index` by one, and increments the project's `version` by one. Merely advancing the logical clock never breaches commitments on its own; only the sweep does.

Reliability decay is tiered, and the tier is always read from the partner's score immediately before the breach. A `reliability_score` of 80 or above loses 5 points; a score of at least 50 but below 80 loses 10; a score below 50 loses 20. A partner sitting at exactly 80 therefore loses 5 — reading the tier from the post-breach score is a different, rejected interpretation. The score never drops below zero. Each breach also adds one to `breach_count`, and when the resulting score falls below 40 while the partner is `ACTIVE`, the partner moves to `PROBATION`. Probation has teeth elsewhere in this document: a probated partner cannot be assigned clashes (§3.4), and a probated partner carrying at least one clash in `ASSIGNED`, `RESOLVED`, or `REOPENED` holds the whole project in `COORDINATION_HOLD` (§2.6). Meetings are listable by `project_id`, `room_id`, and `status`; commitments by `meeting_id`, `clash_issue_id`, `committed_by_partner_id`, and `status`.

### 3.6. Fabrication Packages and Lead-Engineer Sign-Off

Fabrication begins when a `FabricationLead` creates a **FabricationPackage** against a frozen baseline. The payload's `federated_model_id` must reference an assembly of the same project that is currently `FROZEN` — otherwise `ERR_FED_NOT_FROZEN` — and `scope_disciplines` must list between one and three unique disciplines, each with a member model in that assembly (`ERR_SCOPE_DISCIPLINE_NOT_IN_ASSEMBLY`). The caller's `X-User-ID` must identify a trade partner of the project and is recorded as `requesting_partner_id`; the package captures the assembly's current `version` in `pinned_fed_model_version`, sets `required_signoff_count` to the number of scope disciplines, starts with `signed_count` at zero, and opens in `DRAFT`.

Submitting the package for sign-off is the `FabricationLead`'s action and requires the caller's `X-User-ID` to equal the `requesting_partner_id` (`ERR_FORBIDDEN_OWNERSHIP`). From `DRAFT` it moves the package to `SIGNOFF_IN_PROGRESS` and creates one **SignOff** per scope discipline in `REQUESTED`, each recorded under its package through `fabrication_package_id` and pinned to the federated member model of its discipline at that moment — captured as the sign-off's `trade_model_id` — and to that model's current version in `pinned_model_version`. From `SIGNOFF_IN_PROGRESS` the same action is a re-request: every sign-off in `DECLINED` or `REVOKED` returns to `REQUESTED`, while `SIGNED` sign-offs are left untouched. From any other package state the action is rejected with `ERR_PACKAGE_NOT_DRAFT`.

A `LeadEngineer` answers a requested sign-off in one of two ways, and both are gated the same: the sign-off must be `REQUESTED` (`ERR_SIGNOFF_NOT_REQUESTED`), and segregation of duties forbids the engineer from judging their own submission — a caller whose `X-User-ID` equals the pinned model's `submitted_by_user_id` is rejected with `ERR_SOD_SIGNOFF_AUTHOR_CONFLICT`. Signing records the caller as `signer_user_id`, moves the sign-off to `SIGNED`, and recomputes the package's `signed_count`; when the count reaches `required_signoff_count`, the package advances on its own from `SIGNOFF_IN_PROGRESS` to `READY_FOR_RELEASE`. Declining simply moves the sign-off to `DECLINED`, from which a later re-request can recover it.

Revocation is never a manual act. A `SIGNED` sign-off becomes `REVOKED` when the federated model it pins leaves `FROZEN` — through the supersession cascade of §3.2, through a manual unfreeze, or through a `FROZEN` assembly being superseded by a newer one — or when its package is voided. Each revocation recomputes the package's `signed_count`, and a package that falls below its `required_signoff_count` regresses from `READY_FOR_RELEASE` to `SIGNOFF_IN_PROGRESS`.

Releasing the package for fabrication is the `FabricationLead`'s final gate, with ownership enforced as above. The package must be `READY_FOR_RELEASE` (`ERR_PACKAGE_NOT_RELEASABLE`); its federated model must be `FROZEN` or `RELEASED` (`ERR_FED_NOT_FROZEN`); the project posture must be `NORMAL` (`ERR_PROJECT_IN_COORDINATION_HOLD`); the project's `coordination_readiness_index` must be at least 85 (`ERR_CRI_BELOW_RELEASE_THRESHOLD`); and the project phase must be `CONSTRUCTION_DOCUMENTS` or `CONSTRUCTION_ADMINISTRATION` (`ERR_PHASE_TOO_EARLY_FOR_FABRICATION`). A released package stamps `released_at` from the logical clock and reaches its terminal `RELEASED` state.

Voiding abandons a package that has not yet shipped: from `DRAFT`, `SIGNOFF_IN_PROGRESS`, or `READY_FOR_RELEASE` — a `RELEASED` or already-`VOID` package rejects the attempt with `ERR_PACKAGE_ALREADY_FINAL` — the owning `FabricationLead` moves the package to its terminal `VOID` state, and every sign-off not already `REVOKED` becomes `REVOKED`. Packages are listable by `project_id`, `federated_model_id`, `requesting_partner_id`, and `status`; the sign-offs of a package and the sign-offs pinned to a trade model each have their own listing, which is how cascade-created sign-offs are discovered.

### 3.7. As-Built Verification and Model-Based Quantity Extraction

Once construction is underway, trades report what was actually built. A `TradeModelAuthor` creates an **AsBuiltModel** against a basis trade model, supplying the basis `trade_model_id` and free-text `field_verification_notes`. Creation is gated twice: the project phase must be `CONSTRUCTION_ADMINISTRATION` or `CLOSEOUT` (`ERR_PHASE_REQUIREMENT_NOT_MET`), and the basis model must be `ACCEPTED` or `SUPERSEDED` (`ERR_MODEL_NOT_ACCEPTED`) in the same project (`ERR_CROSS_PROJECT_REFERENCE`). The as-built's `trade_partner_id` is copied from the basis model and must equal the caller's `X-User-ID` (`ERR_FORBIDDEN_OWNERSHIP`). The record opens in `DRAFT`, and its `verification_deviation_mm` stays null until verification.

Submitting moves the as-built from `DRAFT` — or, in the field-rework loop, from `REJECTED` — into `SUBMITTED`, with any other from-state rejected as `ERR_AS_BUILT_NOT_SUBMITTABLE` and ownership enforced as at creation. Verification is the `VDCManager`'s call and requires `SUBMITTED` (`ERR_AS_BUILT_NOT_SUBMITTED`). The supplied `verification_deviation_mm` is compared against a tolerance of 25.0 mm: a deviation of at most 25.0 mm — exactly 25.0 included — verifies the record into its terminal `FIELD_VERIFIED` state, while anything beyond rejects it to `REJECTED`. Either way, the measured deviation is recorded on the record. As-builts are listable by `project_id`, `trade_model_id`, `trade_partner_id`, and `status`.

Quantities are extracted from baselines. A `BIMCoordinator` creates a **QuantityTakeoff** against a federated model that is `FROZEN` or `RELEASED` — any other state draws `ERR_FED_NOT_FROZEN` — supplying the `federated_model_id`, an `extraction_mode` of `GROSS` or `NET`, an optional `discipline_filter` restricting the extraction to one discipline, and a non-empty `elements` array whose members each carry an `element_ref`, a `gross_qty`, and a `deduction_qty`, with each gross quantity at least its deduction and neither negative; violations are `ERR_INVALID_REQUEST`. The referenced assembly must belong to the project in the path (`ERR_CROSS_PROJECT_REFERENCE`). Extraction is the second operation guarded by optimistic concurrency under §2.9, so the request must carry `expected_project_version`; a mismatch with the project's current `version` is rejected with `ERR_STALE_PROJECT_VERSION`, because the create supersedes any existing takeoff with the same key and a stale writer must re-read first. The takeoff's `element_count` is the number of supplied elements.

The extracted `total_quantity` depends on the mode, at three decimal places. Under `GROSS`, the gross quantities are summed and the sum is rounded half-up to three decimals, with deductions ignored. Under `NET`, each element's net — its gross minus its deduction — is rounded half-up to three decimals first, and those per-element nets are then summed with no second rounding; summing the raw nets and rounding once at the end is a different, rejected interpretation. Creating the takeoff supersedes any existing takeoff of the same `federated_model_id`, `extraction_mode`, and `discipline_filter`, whether that predecessor is `EXTRACTED` or `APPROVED`; the new takeoff opens in `EXTRACTED`, and the creation increments the project's `version` by one.

Approval belongs to the `VDCManager` and requires the takeoff `EXTRACTED` (`ERR_TAKEOFF_NOT_EXTRACTED`) and its federated model `RELEASED` (`ERR_FED_NOT_RELEASED`); approval moves the takeoff to `APPROVED`. Takeoffs are listable by `project_id`, `federated_model_id`, and `status`.

### 3.8. Closeout Handover to Facilities

The final act of coordination is handing the model record to the owner. A `BIMCoordinator` creates a **HandoverPackage** with a `label` and an `includes_takeoff_id` referencing the quantity takeoff that goes to facilities; the takeoff must exist (`ERR_TAKEOFF_NOT_FOUND`) and belong to the same project (`ERR_CROSS_PROJECT_REFERENCE`). The package opens in `ASSEMBLING`, with `transmitted_at` and `fm_decision_by_user_id` null until their moments arrive.

Marking the package ready is allowed from `ASSEMBLING` — or, in the facilities-rejection rework loop, from `FM_REJECTED` — with any other state rejected as `ERR_HANDOVER_NOT_ASSEMBLING`, and it applies four aggregate gates: the project phase must be `CLOSEOUT` (`ERR_PHASE_REQUIREMENT_NOT_MET`); the referenced takeoff must be `APPROVED` (`ERR_TAKEOFF_NOT_APPROVED`); at least one as-built model must exist in the project and every as-built in the project must be `FIELD_VERIFIED` (`ERR_AS_BUILTS_NOT_VERIFIED`); and no clash anywhere in the project may sit in `NEW`, `ASSIGNED`, `RESOLVED`, or `REOPENED` (`ERR_OPEN_CLASHES_REMAIN`). The same four gates apply identically on the rework loop from `FM_REJECTED`. A ready package sits in `READY`.

Transmitting a `READY` package — any other state draws `ERR_HANDOVER_NOT_READY` — stamps `transmitted_at` from the logical clock and moves it to `TRANSMITTED`. The answer belongs to the `FacilitiesManager`, whose caller identity is recorded in `fm_decision_by_user_id`: responding requires `TRANSMITTED` (`ERR_HANDOVER_NOT_TRANSMITTED`), and the supplied `decision` of `ACCEPT` lands the package in its terminal `FM_ACCEPTED` state while `REJECT` returns it to `FM_REJECTED`, from which the mark-ready rework loop begins again; any other decision value is `ERR_INVALID_REQUEST`. Handover packages are listable by `project_id`, `includes_takeoff_id`, and `status`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including all state-transition actions — return a `200 OK` status code, as do all reads. The table below fixes the HTTP contract for every endpoint; the request payloads, computed fields, and side effects behind each operation are specified by the narratives of §2 and §3, not repeated here. Read endpoints (GET) are open to every role; each mutating endpoint admits the single role listed.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/projects` | Create a project | VDCManager |
| GET | `/api/projects/{id}` | Get a project, including CRI, posture, and counters | Any |
| POST | `/api/projects/{id}/advance-phase` | Advance `current_phase` one step in the fixed order | VDCManager |
| POST | `/api/projects/{id}/run-coordination-sweep` | Breach overdue commitments, apply reliability penalties, recompute CRI and posture | VDCManager |
| POST | `/api/projects/{id}/lod-requirements` | Create a LOD requirement for a discipline and phase | VDCManager |
| GET | `/api/projects/{id}/lod-requirements` | List LOD requirements of a project | Any |
| POST | `/api/projects/{id}/trade-partners` | Onboard a trade partner | VDCManager |
| GET | `/api/projects/{id}/trade-partners` | List trade partners of a project | Any |
| POST | `/api/projects/{id}/trade-models` | Create a trade model revision in `DRAFT`; interop status computed at creation | TradeModelAuthor |
| GET | `/api/trade-models` | List trade models with filters | Any |
| GET | `/api/trade-models/{id}` | Get a trade model | Any |
| POST | `/api/trade-models/{id}/submit` | Submit (or resubmit) a model for coordination review | TradeModelAuthor |
| POST | `/api/trade-models/{id}/accept` | Accept a submitted model; computes audit score and runs the supersession cascade | BIMCoordinator |
| POST | `/api/trade-models/{id}/reject` | Reject a submitted model | BIMCoordinator |
| POST | `/api/projects/{id}/federated-models` | Assemble a federated model from member trade models; supersedes the current non-terminal assembly | VDCManager |
| GET | `/api/federated-models` | List federated models with filters | Any |
| GET | `/api/federated-models/{id}` | Get a federated model | Any |
| POST | `/api/federated-models/{id}/freeze` | Freeze an assembled model; re-pins member versions and clears staleness | VDCManager |
| POST | `/api/federated-models/{id}/unfreeze` | Manually unfreeze a frozen model; revokes dependent signed sign-offs | VDCManager |
| POST | `/api/federated-models/{id}/release` | Issue a frozen model for construction | VDCManager |
| GET | `/api/federated-models/{id}/members` | List members of a federated model | Any |
| GET | `/api/trade-models/{id}/federated-model-members` | List federation memberships of a trade model | Any |
| POST | `/api/federated-models/{id}/freeze-windows` | Schedule a freeze window on a federated model | VDCManager |
| GET | `/api/federated-models/{id}/freeze-windows` | List freeze windows of a federated model | Any |
| POST | `/api/federated-models/{id}/clash-runs` | Create a clash detection run against a `FROZEN` federated model | BIMCoordinator |
| GET | `/api/clash-runs` | List clash runs with filters | Any |
| GET | `/api/clash-runs/{id}` | Get a clash run | Any |
| POST | `/api/clash-runs/{id}/start` | Start a queued run | BIMCoordinator |
| POST | `/api/clash-runs/{id}/clashes` | Import a detected clash into a `RUNNING` run | BIMCoordinator |
| POST | `/api/clash-runs/{id}/complete` | Complete a running run | BIMCoordinator |
| GET | `/api/clash-issues` | List clash issues with filters | Any |
| GET | `/api/clash-issues/{id}` | Get a clash issue | Any |
| POST | `/api/clash-issues/{id}/assign` | Assign or re-assign a clash to an active trade partner of the same project | BIMCoordinator |
| POST | `/api/clash-issues/{id}/resolve` | Claim resolution with actual labor hours; debits the partner's coordination budget | TradeModelAuthor |
| POST | `/api/clash-issues/{id}/verify` | Verify a resolved clash; passing re-inspection verifies, failing reopens | BIMCoordinator |
| POST | `/api/clash-issues/{id}/reopen` | Reopen a verified clash; breaches the fulfilled commitment | BIMCoordinator |
| POST | `/api/projects/{id}/coordination-meetings` | Schedule a coordination meeting | BIMCoordinator |
| GET | `/api/coordination-meetings` | List coordination meetings with filters | Any |
| GET | `/api/coordination-meetings/{id}` | Get a coordination meeting | Any |
| POST | `/api/coordination-meetings/{id}/start` | Start a scheduled meeting inside its window | BIMCoordinator |
| POST | `/api/coordination-meetings/{id}/adjourn` | Adjourn an in-session meeting | BIMCoordinator |
| POST | `/api/coordination-meetings/{id}/commitments` | Record a resolution commitment during an in-session meeting | BIMCoordinator |
| GET | `/api/commitments` | List resolution commitments with filters | Any |
| GET | `/api/commitments/{id}` | Get a resolution commitment | Any |
| POST | `/api/commitments/{id}/waive` | Waive an open commitment | BIMCoordinator |
| POST | `/api/projects/{id}/fabrication-packages` | Create a fabrication package against a `FROZEN` federated model | FabricationLead |
| GET | `/api/fabrication-packages` | List fabrication packages with filters | Any |
| GET | `/api/fabrication-packages/{id}` | Get a fabrication package | Any |
| POST | `/api/fabrication-packages/{id}/submit-for-signoff` | Create or re-request per-discipline sign-offs | FabricationLead |
| POST | `/api/fabrication-packages/{id}/release` | Release a ready package for fabrication | FabricationLead |
| POST | `/api/fabrication-packages/{id}/void` | Void a non-final package; revokes its sign-offs | FabricationLead |
| GET | `/api/fabrication-packages/{id}/signoffs` | List sign-offs of a package | Any |
| GET | `/api/trade-models/{id}/signoffs` | List sign-offs pinned to a trade model | Any |
| GET | `/api/signoffs/{id}` | Get a sign-off | Any |
| POST | `/api/signoffs/{id}/sign` | Sign a requested sign-off | LeadEngineer |
| POST | `/api/signoffs/{id}/decline` | Decline a requested sign-off | LeadEngineer |
| POST | `/api/projects/{id}/as-built-models` | Create an as-built model record against an accepted or superseded trade model | TradeModelAuthor |
| GET | `/api/as-built-models` | List as-built models with filters | Any |
| GET | `/api/as-built-models/{id}` | Get an as-built model | Any |
| POST | `/api/as-built-models/{id}/submit` | Submit (or resubmit) an as-built for field verification | TradeModelAuthor |
| POST | `/api/as-built-models/{id}/verify` | Verify an as-built against the deviation tolerance | VDCManager |
| POST | `/api/projects/{id}/quantity-takeoffs` | Extract model-based quantities from a `FROZEN` or `RELEASED` federated model | BIMCoordinator |
| GET | `/api/quantity-takeoffs` | List quantity takeoffs with filters | Any |
| GET | `/api/quantity-takeoffs/{id}` | Get a quantity takeoff | Any |
| POST | `/api/quantity-takeoffs/{id}/approve` | Approve an extracted takeoff whose federated model is `RELEASED` | VDCManager |
| POST | `/api/projects/{id}/handover-packages` | Create a handover package referencing a quantity takeoff | BIMCoordinator |
| GET | `/api/handover-packages` | List handover packages with filters | Any |
| GET | `/api/handover-packages/{id}` | Get a handover package | Any |
| POST | `/api/handover-packages/{id}/mark-ready` | Mark a handover package ready after the closeout aggregate gates | BIMCoordinator |
| POST | `/api/handover-packages/{id}/transmit` | Transmit a ready handover package to facilities | BIMCoordinator |
| POST | `/api/handover-packages/{id}/respond` | Facilities accepts or rejects a transmitted handover package | FacilitiesManager |
| POST | `/api/_clock/set_current_utc` | Advance the server's logical clock; recomputes clock-dependent derived fields | VDCManager |

## 5. Error Code Catalogue

The catalogue below fixes every error identifier and its HTTP status. The conditions under which each error is raised are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_TRADE_PARTNER_NOT_FOUND` | 404 Not Found |
| `ERR_TRADE_MODEL_NOT_FOUND` | 404 Not Found |
| `ERR_FEDERATED_MODEL_NOT_FOUND` | 404 Not Found |
| `ERR_CLASH_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_CLASH_ISSUE_NOT_FOUND` | 404 Not Found |
| `ERR_MEETING_NOT_FOUND` | 404 Not Found |
| `ERR_COMMITMENT_NOT_FOUND` | 404 Not Found |
| `ERR_PACKAGE_NOT_FOUND` | 404 Not Found |
| `ERR_SIGNOFF_NOT_FOUND` | 404 Not Found |
| `ERR_AS_BUILT_NOT_FOUND` | 404 Not Found |
| `ERR_TAKEOFF_NOT_FOUND` | 404 Not Found |
| `ERR_HANDOVER_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_TIME_RANGE` | 422 Unprocessable Entity |
| `ERR_STALE_PROJECT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_PHASE_TRANSITION` | 409 Conflict |
| `ERR_PHASE_TOO_EARLY_FOR_FABRICATION` | 409 Conflict |
| `ERR_PHASE_REQUIREMENT_NOT_MET` | 409 Conflict |
| `ERR_MODEL_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_MODEL_NOT_SUBMITTED` | 409 Conflict |
| `ERR_MODEL_NOT_ACCEPTED` | 409 Conflict |
| `ERR_LOD_BELOW_PHASE_REQUIREMENT` | 422 Unprocessable Entity |
| `ERR_INTEROP_INCOMPATIBLE_FORMAT` | 422 Unprocessable Entity |
| `ERR_FED_NOT_ASSEMBLED` | 409 Conflict |
| `ERR_FED_NOT_FROZEN` | 409 Conflict |
| `ERR_FED_NOT_RELEASED` | 409 Conflict |
| `ERR_MEMBER_COMPLIANCE_BELOW_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_DISCIPLINE_IN_ASSEMBLY` | 409 Conflict |
| `ERR_CROSS_PROJECT_REFERENCE` | 422 Unprocessable Entity |
| `ERR_FREEZE_WINDOW_ACTIVE` | 409 Conflict |
| `ERR_FREEZE_WINDOW_GAP_VIOLATION` | 409 Conflict |
| `ERR_RUN_NOT_QUEUED` | 409 Conflict |
| `ERR_RUN_NOT_RUNNING` | 409 Conflict |
| `ERR_RUN_HAS_UNASSIGNED_CLASHES` | 409 Conflict |
| `ERR_ROOM_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_MEETING_NOT_SCHEDULED` | 409 Conflict |
| `ERR_MEETING_NOT_IN_SESSION` | 409 Conflict |
| `ERR_MEETING_WINDOW_NOT_ACTIVE` | 409 Conflict |
| `ERR_CLASH_NOT_ASSIGNABLE` | 409 Conflict |
| `ERR_CLASH_NOT_RESOLVABLE` | 409 Conflict |
| `ERR_CLASH_NOT_VERIFIABLE` | 409 Conflict |
| `ERR_CLASH_NOT_REOPENABLE` | 409 Conflict |
| `ERR_TRADE_PARTNER_ON_PROBATION` | 403 Forbidden |
| `ERR_COORDINATION_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_DUPLICATE_TRADE_PARTNER` | 409 Conflict |
| `ERR_COMMITMENT_TRADE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_COMMITMENT_NOT_OPEN` | 409 Conflict |
| `ERR_PACKAGE_NOT_DRAFT` | 409 Conflict |
| `ERR_PACKAGE_NOT_RELEASABLE` | 409 Conflict |
| `ERR_PACKAGE_ALREADY_FINAL` | 409 Conflict |
| `ERR_SCOPE_DISCIPLINE_NOT_IN_ASSEMBLY` | 422 Unprocessable Entity |
| `ERR_SIGNOFF_NOT_REQUESTED` | 409 Conflict |
| `ERR_SOD_SIGNOFF_AUTHOR_CONFLICT` | 403 Forbidden |
| `ERR_SOD_VERIFY_EQUALS_ASSIGN` | 403 Forbidden |
| `ERR_PROJECT_IN_COORDINATION_HOLD` | 409 Conflict |
| `ERR_CRI_BELOW_RELEASE_THRESHOLD` | 409 Conflict |
| `ERR_AS_BUILT_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_AS_BUILT_NOT_SUBMITTED` | 409 Conflict |
| `ERR_TAKEOFF_NOT_EXTRACTED` | 409 Conflict |
| `ERR_TAKEOFF_NOT_APPROVED` | 409 Conflict |
| `ERR_HANDOVER_NOT_ASSEMBLING` | 409 Conflict |
| `ERR_HANDOVER_NOT_READY` | 409 Conflict |
| `ERR_HANDOVER_NOT_TRANSMITTED` | 409 Conflict |
| `ERR_AS_BUILTS_NOT_VERIFIED` | 409 Conflict |
| `ERR_OPEN_CLASHES_REMAIN` | 409 Conflict |
| `ERR_DUPLICATE_LOD_REQUIREMENT` | 409 Conflict |
