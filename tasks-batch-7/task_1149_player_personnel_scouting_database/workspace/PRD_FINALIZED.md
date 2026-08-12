# Player Personnel Scouting API — Product Requirements Document

## 1. Introduction

This document specifies the Player Personnel & Scouting API for a professional team's player personnel department. The department's work spans the full annual talent-acquisition cycle: field scouts author standardized scouting reports on draft-eligible prospects, a scouting director reviews and locks those reports so that cross-scout grading becomes comparable, confidential medical and character flags are raised and adjudicated under strict segregation of duties, draft boards are built and ranked against roster needs, free-agency targets are pursued against a season budget, and post-draft outcomes are tracked so that scout accuracy itself can be evaluated.

The API exists to replace an ad-hoc mix of spreadsheets, shared drives, and verbal hand-offs with a single authoritative system. Three structural pressures shape the design. First, confidentiality: medical and character information is compartmentalized — medical staff, scouting staff, and the front office each see only what their role permits, and certain medical escalations have immediate draft-board consequences. Second, comparability: raw grades from different scouts are not directly comparable, so every locked grade is normalized against its author's historical grading distribution before it feeds a prospect's composite. Third, auditability and recovery: the draft board freezes and unfreezes as the season unfolds, free-agency signings are reversible through release, and every mutating operation on a board or budget carries an optimistic-concurrency guarantee so that two staff members never silently overwrite each other's work.

A test-driving logical clock is exposed for evaluation harnesses. Before any call to set it, the server's logical clock is exactly `2026-05-01T00:00:00Z`, and it never falls back to wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes four distinct roles, spelled exactly: `AreaScout`, `ScoutingDirector`, `MedicalStaff`, and `GeneralManager`. A request missing either header, or carrying a role string that is not one of these four, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Access to specific operations is further restricted by role; an attempt to perform an action outside the caller's designated role is rejected with `ERR_FORBIDDEN` (HTTP 403).

Two roles are **entity-backed** by the `Scout` registry, and two are **opaque**:

- When `X-User-Role` is `AreaScout`, `X-User-ID` is the `id` of the acting `Scout`, and that Scout row's `level` must be `AREA`. Ownership checks on any resource that references a `Scout` (for example a `ScoutingReport`'s `scout_id`) compare the resource's foreign-key field to `X-User-ID`.
- When `X-User-Role` is `ScoutingDirector`, `X-User-ID` is the `id` of the acting `Scout`, and that Scout row's `level` must be `DIRECTOR`. A scout whose `level` does not match the claimed role is rejected with `ERR_FORBIDDEN`.
- When `X-User-Role` is `MedicalStaff`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `author_role` on a `ConfidentialFlag`) but does not compare it to any entity's `id`.
- When `X-User-Role` is `GeneralManager`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity.

Beyond role-gating, two finer-grained ownership rules apply. Only the authoring scout — that is, a caller whose `X-User-ID` equals the report's `scout_id` — may submit that report or attach video tags to it; any other scout attempting either is rejected with `ERR_REPORT_NOT_OWNED` (HTTP 403). And flag creation is compartmentalized by clearance: a `MEDICAL` flag may be created only by `MedicalStaff`, while a `CHARACTER` flag may be created only by an `AreaScout` or `ScoutingDirector`; crossing that boundary is rejected with `ERR_FLAG_ACCESS_DENIED` (HTTP 403).

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

List endpoints are paginated via two query parameters. `limit` specifies the maximum number of items to return; if omitted it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the system — `Scout`, `Prospect`, `ScoutingReport`, `ConfidentialFlag`, `DraftBoard`, `DraftBoardEntry`, `RosterNeed`, `FreeAgentTarget`, `Budget`, `InterviewSession`, `Facility`, `FacilityBooking`, and `OutcomeRecord` — carries a standard set of system-managed fields:

- **`id` (string):** a unique, server-generated identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was last modified; refreshed on every mutation.
- **`version` (integer):** a system-managed integer that increments by exactly 1 on every mutation to the resource, and is the basis for optimistic concurrency control.

`VideoTag` is the sole exception. A video tag carries `id` and `created_at` only — it has no `updated_at` and no `version`, because it is immutable after creation.

Mutations that the server performs as cascades — recomputing a prospect's `composite_grade`, reranking a board and rewriting its entries' `rank` values, recomputing a budget's `committed_cents` — count as mutations on the affected entity and therefore refresh that entity's `updated_at` and increment its `version`. This is the mechanism by which a client holding a previously-read `version` detects that something it cares about has changed underneath it.

### 2.5. Numeric Precision and Rounding

Grades, fit scores, and accuracy metrics in this system are decimal quantities; money is integer cents. The conventions are:

- All grade-scale quantities (`raw_grade`, `normalized_grade`, `composite_grade`, per-scout means and standard deviations, `scheme_fit`, `fit_score`, accuracy metrics) are represented with exactly 2 decimal places, using round-half-up. Values supplied with more than 2 decimal places are rejected as invalid.
- Tier thresholds compare against the 2-decimal `composite_grade` using inclusive lower bounds — a composite of exactly 7.00 is in the second tier, not the third.
- All monetary quantities (`base_cap_cents`, `rollover_cents`, `committed_cents`, `available_cents`, `base_salary_cents`, `signing_bonus_cents`, `annual_cap_hit_cents`, `rollover_delta_cents`) are integer cents. The only rounding applied to money is the round-half-up of the signing-bonus proration when computing a target's year-one cap hit.
- A prospect's `composite_grade` and `tier`, and a scouting report's `normalized_grade`, remain `null` until the computation that produces them has run at least once; they are never zero-filled.

### 2.6. Optimistic Concurrency Control

Two write operations in the system are OCC-guarded against a named parent aggregate. Each requires the request body to carry a client-supplied version field naming the client's last-observed `version` of the parent; if the value does not match the parent's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no mutation occurs. The two guarded operations are:

- **Manual reorder of a draft board's entries.** The request must carry `expected_board_version` equal to the board's current `version`. Because a report lock, a flag-exclusion cascade, a scout weight change, or another writer's reorder each increment the board's `version`, a client holding a stale view is prevented from re-imposing a ranking computed on data it has not observed.
- **Posting a rollover adjustment against a budget.** The request must carry `expected_budget_version` equal to the budget's current `version`. Because signings and releases increment the budget's `version`, a client is prevented from applying a rollover delta on top of a `committed_cents` baseline it has not observed.

No other endpoint takes a version field; mutations not listed above are not OCC-guarded.

### 2.7. Confidentiality and Segregation of Duties

The department enforces a strict segregation: no single role spans the full flag lifecycle, the medical pipeline, and the fiscal pipeline.

`MedicalStaff` is the sole author of `MEDICAL` flags and the sole role that ever sees a MEDICAL flag's `detail` field unredacted; for any other role reading flags, the `detail` of a `MEDICAL` flag is returned as `null`. `AreaScout` and `ScoutingDirector` author `CHARACTER` flags; `MedicalStaff` may not. Acknowledging and resolving a flag is reserved for the role family that owns its type — `MedicalStaff` for `MEDICAL`, `ScoutingDirector` for `CHARACTER`. Escalation, the most consequential flag action, is exclusively a `ScoutingDirector` power, regardless of flag type. The front-office `GeneralManager` owns scouts, budgets, roster needs, free-agency targets, facilities, and the post-draft record, but cannot author reports, lock grades, or touch flags.

### 2.8. Resource Existence and Left-to-Right Path Validation

For any endpoint whose path or body references existing resources — a `prospect_id` in the path, a `budget_id` in a sign payload, an `entry_id` in a reorder payload — the system validates existence of every referenced identifier in left-to-right order, rejecting with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve. Existence is checked before state and business rules, so a request targeting a non-existent prospect receives 404 even if the request body would also fail validation.

### 2.9. Validation Ordering

When multiple validation rules apply to a single request, they are evaluated in a fixed priority order, and the request fails at the first violated rule with that rule's error code:

1. Authentication — headers present and role declared (`ERR_UNAUTHENTICATED`).
2. Authorization — role permitted on the endpoint, entity-backed identity's scout `level` matches, report-ownership on submit / video-tag, flag-type clearance on flag creation (`ERR_FORBIDDEN`, `ERR_REPORT_NOT_OWNED`, `ERR_FLAG_ACCESS_DENIED`).
3. Request schema — required fields present, types correct, enum values in range, end strictly after start on temporal pairs, integers non-negative where declared (`ERR_VALIDATION`).
4. Existence — every referenced id resolves (`ERR_NOT_FOUND`).
5. State guards — the entity's current state permits the transition, plus the endpoint-specific state rules: report creation allowed only while the prospect is pre-draft, board mutations only while the board is `OPEN`, entry adds only for `BOARD_READY` prospects, finalize only on a non-empty board, sign only on an `OFFERED` target, advance to `APPROVED` only with a matching open need, outcome records only for `DRAFTED` prospects (`ERR_INVALID_STATE`, `ERR_BOARD_NOT_OPEN`, `ERR_PROSPECT_NOT_BOARD_READY`, `ERR_BOARD_EMPTY`, `ERR_TARGET_NOT_OFFERED`, `ERR_NO_ROSTER_NEED`, `ERR_OUTCOME_NOT_DRAFTED`).
6. Business safety — interview scheduling blocked by open flag review, entry add blocked by prospect exclusion (`ERR_FLAG_REVIEW_OPEN`, `ERR_PROSPECT_EXCLUDED`).
7. Business constraints — report uniqueness, grade ranges, reorder bounds, weight positivity (`ERR_DUPLICATE_REPORT`, `ERR_GRADE_OUT_OF_RANGE`, `ERR_RANK_OUT_OF_BOUNDS`, `ERR_WEIGHT_INVALID`).
8. Temporal constraints — interview overlap, facility buffer (`ERR_INTERVIEW_OVERLAP`, `ERR_FACILITY_BUFFER_CONFLICT`).
9. Fiscal constraints — sign gate and budget-adjustment floor (`ERR_BUDGET_EXCEEDED`).

## 3. Business Logic & Workflows

### 3.1. Scouting Staff and the Season's Grading Baseline

A `GeneralManager` registers each member of the scouting staff as a `Scout`, supplying a `full_name` and a `level` of either `AREA` or `DIRECTOR`. The `level` is not decorative — it is the identity anchor for role checks: an `X-User-ID` presented with role `AreaScout` must resolve to a Scout whose `level` is `AREA`, and similarly `ScoutingDirector` requires `DIRECTOR`. Each scout also carries a board `weight`, defaulting to 1.0 when omitted, which governs how strongly that scout's locked grades pull a prospect's composite; a weight must be strictly greater than zero, and an attempt to set a non-positive weight is rejected with `ERR_WEIGHT_INVALID`.

Two pairs of season statistics live on each scout. The **provisional pair** — `season_grade_mean` and `season_grade_stdev` — describes the scout's in-season raw-grade distribution and is what the system uses to normalize grades during the season. The **final pair** — `locked_grade_mean` and `locked_grade_stdev` — is the offseason-locked full-season distribution. Either value of either pair may be `null` when not yet established; when set, the means must lie between 1.00 and 9.00 inclusive and the standard deviations must be strictly greater than zero. The mere presence of `locked_grade_mean` (signalling the director has published the offseason lock) is what switches the normalization variant from provisional to final — see §3.3.

A `ScoutingDirector` may revise a scout's board `weight` mid-season by supplying `new_weight`. Because the composite is weight-sensitive, changing a weight recomputes the `composite_grade` and `tier` of every prospect with at least one `LOCKED` report authored by that scout, and reruns the rerank of every `OPEN` board on which any affected prospect has an active entry. The scout's own `version` increments by 1 on this operation.

### 3.2. Building the Prospect Pool

An `AreaScout` or `ScoutingDirector` creates a `Prospect` profile with a `full_name`, a free-form uppercase `position` code such as QB or OT, and a `college`. Every prospect moves through two **independent** lifecycle dimensions.

The first dimension, `evaluation_status`, tracks the evaluation pipeline: `NEW` → `SCOUTING` → `EVALUATED` → `BOARD_READY` → `DRAFTED`, with `ARCHIVED` available as a terminal off-ramp from `EVALUATED` or `BOARD_READY`. The transition from `NEW` to `SCOUTING` is not operator-driven — it happens automatically in the same request that creates the prospect's first scouting report. From `SCOUTING`, a `ScoutingDirector` advances the prospect by supplying a `to_state` of `EVALUATED`, but only once at least one report on the prospect has been `LOCKED`; the same one-locked-report precondition gates `EVALUATED` → `BOARD_READY`. Either `EVALUATED` or `BOARD_READY` may instead be advanced with a `to_state` of `ARCHIVED` to retire the prospect from consideration. Only a `GeneralManager` may mark a `BOARD_READY` prospect as drafted, moving `evaluation_status` to `DRAFTED`. Any other advance combination — skipping states, reversing, advancing from a state without a locked report where one is required — is rejected with `ERR_INVALID_STATE`.

The second dimension, `flag_status`, tracks the prospect's confidential-flag posture and evolves independently: `CLEAR`, `UNDER_REVIEW`, `CLEARED`, or `EXCLUDED`. A prospect begins at `CLEAR`. The creation of any confidential flag moves the prospect to `UNDER_REVIEW` in the same request. Resolving a flag moves the prospect to `CLEARED` — but only when no other flag of that prospect remains in `OPEN`, `ACKNOWLEDGED`, or `ESCALATED`; otherwise the prospect stays `UNDER_REVIEW`. Escalating a `HIGH`-severity `MEDICAL` flag moves the prospect to `EXCLUDED`, a posture with draft-board consequences described in §3.6. A prospect already `CLEARED` returns to `UNDER_REVIEW` if a new flag is later created. Once `EXCLUDED`, resolution of the causative flag does **not** reverse the exclusion — the prospect remains `EXCLUDED` for the season.

### 3.3. The Scouting Report Lifecycle and Cross-Scout Normalization

An `AreaScout` authors a `ScoutingReport` against a prospect by supplying a `raw_grade` on the team's 1.00–9.00 scale and a `scheme_fit` multiplier between 0.00 and 1.50, both with at most 2 decimal places; values outside those ranges are rejected with `ERR_GRADE_OUT_OF_RANGE`. Free-text `notes` may accompany the report and default to an empty string. Report creation is permitted only while the prospect's `evaluation_status` is `NEW`, `SCOUTING`, or `EVALUATED` — a prospect already `BOARD_READY`, `DRAFTED`, or `ARCHIVED` accepts no new reports. At most one report per scout per prospect exists: a second creation attempt by the same scout against the same prospect is rejected with `ERR_DUPLICATE_REPORT`. The report's `scout_id` is taken from the caller's `X-User-ID`, never from the request body.

A report is born in `DRAFT`. The authoring scout — and only that scout, with any other submitter rejected as `ERR_REPORT_NOT_OWNED` — submits it, moving it to `SUBMITTED`. From `SUBMITTED` a `ScoutingDirector` has two moves: return the report for revision, recording a `return_reason` (defaulting to an empty string when omitted), which moves it to `RETURNED`; or lock it, which is terminal. A returned report may be resubmitted by its author, moving `RETURNED` → `SUBMITTED` and clearing the stored `return_reason` in the process. The revision loop `SUBMITTED` → `RETURNED` → `SUBMITTED` may iterate as many times as needed before lock.

A report's subject prospect is recorded in its `prospect_id` field, and the report in turn is the unit against which video tags (each holding a `report_id`) are attached.

Locking is the consequential moment. When the director locks a report, four cascades run in order:

1. The report's `normalized_grade` is computed and snapshotted onto the report. The system computes a z-score by subtracting the applicable mean from the report's `raw_grade` and dividing by the applicable standard deviation, then maps the z-score back onto the team scale by multiplying by 1.5 and adding 5.0, rounds the result half-up to 2 decimal places, and clamps it into the inclusive range 1.00 to 9.00. The applicable mean and standard deviation are chosen by variant: if the authoring scout's `locked_grade_mean` is null (in-season), the **provisional** variant uses the scout's `season_grade_mean` and `season_grade_stdev`; once the scout's `locked_grade_mean` is set (offseason lock published), the **final** variant uses `locked_grade_mean` and `locked_grade_stdev`. Because the two statistic pairs generally differ, the same `raw_grade` yields a different `normalized_grade` under the two variants. The chosen pair is snapshotted into the report at lock time, so a later update to the scout's season stats does not retroactively change already-locked grades.
2. The prospect's `composite_grade` and `tier` are recomputed. The composite considers **only** `LOCKED` reports for the prospect — `DRAFT`, `SUBMITTED`, and `RETURNED` reports are excluded. Each locked report contributes in proportion to its author's `weight`: the system divides each report's author's weight by the sum of weights across all locked reports' authors to obtain that report's weight fraction, multiplies the fraction by the report's `normalized_grade`, and rounds the resulting contribution half-up to 2 decimal places **per report first**. The per-report rounded contributions are then summed, and the sum is itself rounded half-up to 2 decimal places to produce the `composite_grade`. Summing unrounded products and rounding once is a different, forbidden order. If the prospect has no locked reports, `composite_grade` and `tier` are both `null`. Tier assignment then maps the composite onto a bucket with inclusive lower bounds: 8.00 or above is `T1`, 7.00 up to but not including 8.00 is `T2`, 6.00 up to but not including 7.00 is `T3`, and anything below 6.00 is `T4`. Exactly 7.00 is `T2`; 6.99 is `T3`.
3. Every `DraftBoardEntry` for this prospect that is still `active` on a board whose `status` is `OPEN` has its `fit_score` recomputed per §3.5, and the rerank runs on each affected board.
4. Each reranked board's `version` is incremented by 1 and its `updated_at` refreshed — the signal by which any client holding a prior board `version` discovers the reorder basis has moved.

While a report is in `DRAFT` or `RETURNED`, its author may attach `VideoTag` entries linking film to the report — each tag carries a `clip_url`, an integer `start_sec` at or above zero, an integer `end_sec` strictly greater than `start_sec`, and a `tag` category of `SCHEME`, `ATHLETICISM`, `TECHNIQUE`, or `CHARACTER`. The ownership guard applies here too: only the report's author may attach tags.

### 3.4. Confidential Flags: Creation, Review, and Escalation

A confidential flag is raised against a prospect by supplying a `flag_type` of `MEDICAL` or `CHARACTER`, a `severity` of `LOW` or `HIGH`, and a free-text `detail` narrative. The clearance rules of §2.7 govern who may create which type: `MEDICAL` only from `MedicalStaff`, `CHARACTER` only from `AreaScout` or `ScoutingDirector`. The system records the creator's `X-User-Role` in the flag's `author_role` field for audit. Flag creation immediately moves the prospect's `flag_status` to `UNDER_REVIEW` in the same request — and, per §3.6, an `UNDER_REVIEW` posture blocks interview scheduling until the review resolves.

A flag is born `OPEN`. The reviewing role — `MedicalStaff` for a `MEDICAL` flag, `ScoutingDirector` for a `CHARACTER` flag — may acknowledge it, moving it to `ACKNOWLEDGED`. From `OPEN`, `ACKNOWLEDGED`, or `ESCALATED`, the appropriate reviewing role may resolve it, optionally recording a `resolution_note`; resolution is terminal. On resolution the prospect's `flag_status` is recomputed: if no other flag of the prospect remains in `OPEN`, `ACKNOWLEDGED`, or `ESCALATED`, the prospect moves `UNDER_REVIEW` → `CLEARED`; otherwise the posture stays `UNDER_REVIEW`. An exclusion that has already occurred is not unwound by resolution.

Escalation is the director's instrument for surfacing a flag with board-level consequences. From `OPEN` or `ACKNOWLEDGED`, a `ScoutingDirector` escalates the flag to `ESCALATED`. The cascade then branches on type and severity: if the flag is `MEDICAL` with severity `HIGH`, the prospect's `flag_status` becomes `EXCLUDED` and the exclusion cascade of §3.6 runs; in every other case — a `LOW` medical flag, or any `CHARACTER` flag — the prospect simply remains (or stays) `UNDER_REVIEW` with no board impact.

### 3.5. Draft Board Construction: Fit Scoring and Rerank

A `ScoutingDirector` creates a `DraftBoard` for a `season_year`; a board is born `OPEN`. Each `DraftBoardEntry` carries the owning board's `board_id` and the ranked prospect's `prospect_id`. While `OPEN`, the director adds entries — one per prospect — by supplying the `prospect_id`. Entry add is gated three ways: the board must be `OPEN` (a `FROZEN` or `FINALIZED` board rejects with `ERR_BOARD_NOT_OPEN`); the prospect's `evaluation_status` must be `BOARD_READY` (otherwise `ERR_PROSPECT_NOT_BOARD_READY`); and the prospect's `flag_status` must not be `EXCLUDED` (otherwise `ERR_PROSPECT_EXCLUDED`). On a successful add, the system computes the entry's `fit_score`, runs the rerank, and increments the board's `version` by 1.

**Fit score** combines roster need, the prospect's best locked grade, and the prospect's flag posture into a single 0–100 number with 2 decimal places:

- The **base need** comes from `RosterNeed` rows matching the prospect's `position`, the board's `season_year`, and `status` `OPEN`. If no such need exists, the base is 20.0. Otherwise the base is read from the highest-`priority_tier` matching need — `P1` outranks `P2`, which outranks `P3`, which outranks `P4` — with ties between equal-priority needs broken by earliest `created_at`. The base values are 90.0 for `P1`, 70.0 for `P2`, 50.0 for `P3`, and 30.0 for `P4`.
- The **scheme multiplier** is the `scheme_fit` of the prospect's locked report with the highest `normalized_grade`, with ties broken by the report's earlier `created_at`.
- The **medical multiplier** is 0.8 whenever any flag of the prospect has `flag_type` `MEDICAL`, `severity` `HIGH`, and `status` `RESOLVED`; otherwise it is 1.0. (A resolved high-severity medical flag therefore continues to discount fit even though the prospect is no longer excluded.)
- The **character deduction** is 15.0 whenever any flag of the prospect has `flag_type` `CHARACTER` and `status` `OPEN` or `ACKNOWLEDGED`; otherwise it is 0. (A character flag that has been escalated or resolved no longer deducts.)
- The fit score is then the base need, multiplied by the scheme multiplier, multiplied by the medical multiplier, minus the character deduction, clamped into the inclusive range 0.0 to 100.0, and rounded half-up to 2 decimal places.

**Rerank** is the board's ordering invariant and runs on entry creation, on the report-lock cascade, on the flag-exclusion cascade, and after any manual reorder. The board's `active` entries are sorted by the prospect's `composite_grade` descending with nulls placed last, then by the entry's `fit_score` descending, then by the entry's `created_at` ascending as the final tie-break — never by id. `rank` is then reassigned contiguously from 1 to N in that order, so deactivating an entry closes the gap it leaves. The board's `active_entry_count` is maintained as the count of entries with `active` equal to `true` and is updated by every cascade that changes it.

**Manual reorder** lets the director move one active entry to a specified `new_rank` by supplying `entry_id`, `new_rank`, and the OCC field `expected_board_version` per §2.6. The reorder uses insert semantics: the named entry is removed from its current position, the remaining entries shift to close the gap, and the named entry is inserted at `new_rank`. `new_rank` must lie between 1 and the board's `active_entry_count` inclusive, and `entry_id` must name an active entry of this board; violations are rejected with `ERR_RANK_OUT_OF_BOUNDS`. A successful reorder reassigns ranks contiguously from 1 and increments the board's `version` by 1.

A board's lifecycle is `OPEN` → `FROZEN` → `FINALIZED`, with an `OPEN` ↔ `FROZEN` cycle: the director freezes an `OPEN` board, may unfreeze a `FROZEN` board back to `OPEN`, and may finalize a `FROZEN` board. Finalization requires at least one active entry — a `FROZEN` board whose `active_entry_count` is zero rejects with `ERR_BOARD_EMPTY`. `FINALIZED` is terminal. Any state-inconsistent freeze, unfreeze, or finalize attempt is rejected with `ERR_INVALID_STATE`.

### 3.6. The Exclusion Cascade

The most consequential automated flow in the system is the cascade triggered when a `HIGH`-severity `MEDICAL` flag is escalated. Three things happen in order: the prospect's `flag_status` becomes `EXCLUDED`; every `DraftBoardEntry` for this prospect on a board whose `status` is `OPEN` or `FROZEN` has its `active` flag set to `false` (entries on `FINALIZED` boards are untouched); and the rerank runs on each affected board, closing the rank gaps left by the deactivated entries, with each reranked board's `version` incremented by 1 and `updated_at` refreshed.

Note the asymmetry with the lock cascade: the lock cascade only touches `OPEN` boards, because a `FROZEN` board's fit scores are meant to be stable; but exclusion deactivates entries on `OPEN` **and** `FROZEN` boards, because an excluded prospect must not appear as draftable anywhere the board is still capable of being finalized.

Because deactivation sets `active` to `false`, excluded prospects drop out of the rerank's active set, and the board's `active_entry_count` reflects the reduced pool.

### 3.7. Roster Needs, Free Agency, and the Season Budget

A `GeneralManager` declares a `RosterNeed` for a `season_year` and `position`, with a `priority_tier` of `P1`, `P2`, `P3`, or `P4`. A need is born `OPEN` and feeds both fit-score base selection (§3.5) and free-agency target approval. Closing a need moves it to `CLOSED`, from which it no longer feeds either — closing is terminal.

Free agency proceeds against a `Budget`, created by the `GeneralManager` with a `season_year`, a `base_cap_cents`, and a `rollover_cents`. A budget carries three derived quantities maintained by the system: `committed_cents`, the sum of `annual_cap_hit_cents` across all `FreeAgentTarget` rows with `status` `SIGNED` against this budget; `available_cents`, defined as the base cap plus rollover minus committed; and `posture`, which is `TIGHT` whenever available is strictly less than one-tenth of the sum of base cap and rollover, and `HEALTHY` otherwise — available equal to exactly one-tenth of that sum is `HEALTHY`, not `TIGHT`. A freshly created budget has `committed_cents` of 0 and is typically `HEALTHY`.

A `GeneralManager` adds a `FreeAgentTarget` with a `player_name`, `position`, `season_year`, `base_salary_cents`, `signing_bonus_cents`, and `contract_years` (at least 1). At creation the system computes and stores the target's `annual_cap_hit_cents`: the year-one cap hit is the base salary plus the signing bonus prorated across the contract years, with the proration rounded half-up to the nearest cent and the total expressed in integer cents. A target is born `IDENTIFIED` and moves through a front-office pipeline: `IDENTIFIED` → `EVALUATING` → `APPROVED` → `OFFERED` → `SIGNED`, with `PASSED` available as a terminal off-ramp from any of `IDENTIFIED`, `EVALUATING`, `APPROVED`, or `OFFERED`, and `RELEASED` as the terminal state reachable only from `SIGNED`. Advance is driven by the `GeneralManager` supplying a `to_state`. The step from `EVALUATING` to `APPROVED` is gated by roster need: an `OPEN` `RosterNeed` whose `position` equals the target's `position` and whose `season_year` equals the target's `season_year` must exist, otherwise the advance is rejected with `ERR_NO_ROSTER_NEED`.

Signing is the fiscal gate. A `GeneralManager` signs an `OFFERED` target against a budget by supplying a `budget_id`; a target in any other state rejects with `ERR_TARGET_NOT_OFFERED`. The gate compares the target's `annual_cap_hit_cents` against the budget's `available_cents` **as computed before** applying the new signing: the signing is allowed only if the cap hit is less than or equal to available — equality is permitted — and is otherwise rejected with `ERR_BUDGET_EXCEEDED`. On a successful signing, the target's `signed_budget_id` is recorded (this field remains `null` until signing and is a plain reference, not an integrity foreign key), the budget's `committed_cents`, `available_cents`, and `posture` are recomputed per the formulas above, and the budget's `version` is incremented by 1.

Release is the compensating action: releasing a `SIGNED` target moves it to `RELEASED`, after which its cap hit no longer counts toward `committed_cents`; the budget named by the target's `signed_budget_id` has `committed_cents`, `available_cents`, and `posture` recomputed accordingly, and its `version` is incremented by 1.

Rollover adjustments let the front office correct a budget mid-season: a `GeneralManager` posts a signed `rollover_delta_cents` together with the OCC field `expected_budget_version` per §2.6. The adjustment adds the delta to the budget's `rollover_cents`, recomputes `available_cents` and `posture`, and increments the budget's `version` by 1. An adjustment whose result would drive `available_cents` below zero is rejected with `ERR_BUDGET_EXCEEDED`.

### 3.8. Interviews, Facilities, and the Calendar

Pre-draft interviews occupy a prospect's calendar. An `AreaScout` or `ScoutingDirector` schedules an `InterviewSession` for a prospect by supplying `start_at`, `end_at` (strictly after `start_at`), and a `location` label; the session is born `SCHEDULED`. Two constraints guard scheduling. First, a safety constraint: while the prospect's `flag_status` is `UNDER_REVIEW` — that is, while any confidential review is open — interview scheduling is blocked outright with `ERR_FLAG_REVIEW_OPEN`. Second, a temporal constraint: the new session's half-open interval may not overlap any `SCHEDULED` session of the same prospect; half-open semantics mean a new session whose `start_at` equals an existing session's `end_at`, or whose `end_at` equals an existing session's `start_at`, is allowed, and any stricter overlap is rejected with `ERR_INTERVIEW_OVERLAP`. Either party may cancel a `SCHEDULED` session, moving it to `CANCELLED`; a cancelled session no longer occupies the prospect's calendar for overlap checks.

Facilities are booked independently of prospects. A `GeneralManager` registers a `Facility` with a `name` and a `capacity` of at least 1. Each `FacilityBooking` records the booked room's `facility_id`. A `GeneralManager` or `ScoutingDirector` books it by supplying `start_at`, `end_at` (strictly after `start_at`), and a `purpose` label. Bookings on the same facility must leave a buffer of at least 30 minutes on both sides: the new booking's `start_at` must be at or after the existing booking's `end_at` plus 30 minutes, or its `end_at` must be at or before the existing booking's `start_at` minus 30 minutes. A gap of exactly 30 minutes is permitted; anything tighter is rejected with `ERR_FACILITY_BUFFER_CONFLICT`.

### 3.9. Post-Draft Outcomes and Scout Evaluation

After the draft, a `GeneralManager` records an `OutcomeRecord` for a `DRAFTED` prospect — recording against any other evaluation state is rejected with `ERR_OUTCOME_NOT_DRAFTED` — supplying the `season_year`, the integer `games_started` (zero or more), the boolean `pro_bowl`, and an analyst-assessed `outcome_percentile` between 0 and 100 inclusive.

These outcomes feed the per-scout evaluation read, computed on demand when a `GeneralManager` or `ScoutingDirector` fetches a scout's evaluation. Two complementary accuracy metrics are reported, alongside the count of evaluated reports:

- The **eligible set** is the scout's `LOCKED` reports whose subject prospect has at least one `OutcomeRecord`. For each eligible report, the comparison outcome is that prospect's `OutcomeRecord` with the maximum `season_year` — the latest season on record.
- **RMSE accuracy** penalizes magnitude of grade error across all eligible reports. Each report's error is its `normalized_grade` minus the outcome's `outcome_percentile` divided by 10 (mapping the 0–100 percentile onto the grade scale). The root-mean-square of these errors is taken, and the accuracy is 100 minus ten times that root-mean-square, rounded half-up to 2 decimal places, floored at 0.
- **Hit-rate accuracy** is a binary hit/miss metric on high-grade predictions only. The predictions are the eligible reports whose `normalized_grade` is at least 7.00; a prediction is a hit when its outcome's `outcome_percentile` is at least 70. Hit-rate accuracy is 100 times the number of hits divided by the number of predictions, rounded half-up to 2 decimal places.
- When the eligible set is empty, both accuracy metrics are `null` and `evaluated_report_count` is 0.

Because the two metrics measure different things — one punishes the size of every miss, the other only counts whether high grades panned out — the same underlying data generally yields two different accuracy numbers, and both are always reported together in the response alongside `scout_id` and `evaluated_report_count`.

## 4. Endpoint Definitions

Operations that create new stand-alone resources (a scout, a prospect, a draft board, a budget, a facility) or add new distinct resources to a collection (a report under a prospect, a flag, a board entry, a video tag, a booking, an interview, an outcome record, a roster need, a free-agent target) return `201 Created`. Operations that modify an existing resource — submit, return, lock, advance, sign, release, pass, freeze, unfreeze, finalize, acknowledge, resolve, escalate, cancel, close, mark drafted, reorder, adjust, set weight — return `200 OK`. The test-driving clock endpoint returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Test-driving logical clock; accepts `to_iso8601`, returns `current_utc`; server default before any call is exactly 2026-05-01T00:00:00Z | GeneralManager, ScoutingDirector, AreaScout, MedicalStaff |
| POST | `/scouting/scouts` | Register a scout | GeneralManager |
| GET | `/scouting/scouts/{id}` | Fetch one scout | GeneralManager, ScoutingDirector, AreaScout, MedicalStaff |
| GET | `/scouting/scouts/{id}/evaluation` | Computed post-draft scout accuracy read (both variants) | GeneralManager, ScoutingDirector |
| POST | `/scouting/scouts/{id}/weight` | Change a scout's board weight; recomputes affected composites and tiers, reranks affected OPEN boards | ScoutingDirector |
| POST | `/scouting/prospects` | Create a prospect profile | AreaScout, ScoutingDirector |
| GET | `/scouting/prospects` | List prospects; filters `position`, `evaluation_status`, `flag_status` | GeneralManager, ScoutingDirector, AreaScout, MedicalStaff |
| GET | `/scouting/prospects/{id}` | Fetch one prospect | GeneralManager, ScoutingDirector, AreaScout, MedicalStaff |
| POST | `/scouting/prospects/{id}/advance` | Advance `evaluation_status` to `EVALUATED`, `BOARD_READY`, or `ARCHIVED` | ScoutingDirector |
| POST | `/scouting/prospects/{id}/mark-drafted` | Mark a BOARD_READY prospect as drafted | GeneralManager |
| GET | `/scouting/prospects/{id}/board-entries` | List draft board entries referencing this prospect | ScoutingDirector, GeneralManager |
| POST | `/scouting/prospects/{id}/reports` | Create a DRAFT scouting report; first report moves prospect NEW to SCOUTING | AreaScout |
| GET | `/scouting/reports` | List scouting reports; filters `scout_id`, `prospect_id`, `status` | AreaScout, ScoutingDirector, GeneralManager |
| GET | `/scouting/reports/{id}` | Fetch one scouting report | AreaScout, ScoutingDirector, GeneralManager |
| POST | `/scouting/reports/{id}/submit` | Submit a DRAFT or RETURNED report (authoring scout only) | AreaScout |
| POST | `/scouting/reports/{id}/return` | Return a SUBMITTED report for revision | ScoutingDirector |
| POST | `/scouting/reports/{id}/lock` | Lock a SUBMITTED report; computes normalized grade and runs prospect-to-board cascade | ScoutingDirector |
| POST | `/scouting/reports/{id}/video-tags` | Attach a video clip tag to a DRAFT or RETURNED report (author only) | AreaScout |
| GET | `/scouting/reports/{id}/video-tags` | List video tags of a report | GeneralManager, ScoutingDirector, AreaScout, MedicalStaff |
| POST | `/scouting/prospects/{id}/flags` | Raise a confidential flag; MEDICAL only by MedicalStaff, CHARACTER only by scouting roles | MedicalStaff, AreaScout, ScoutingDirector |
| GET | `/scouting/prospects/{id}/flags` | List flags of a prospect; MEDICAL `detail` redacted to null for non-MedicalStaff; filters `flag_type`, `status` | GeneralManager, ScoutingDirector, AreaScout, MedicalStaff |
| POST | `/scouting/flags/{id}/acknowledge` | Acknowledge an OPEN flag | MedicalStaff, ScoutingDirector |
| POST | `/scouting/flags/{id}/resolve` | Resolve a flag; recomputes prospect flag_status | MedicalStaff, ScoutingDirector |
| POST | `/scouting/flags/{id}/escalate` | Escalate a flag; HIGH MEDICAL excludes the prospect and deactivates board entries | ScoutingDirector |
| POST | `/scouting/draft-boards` | Create a draft board for a season | ScoutingDirector |
| GET | `/scouting/draft-boards/{id}` | Fetch one draft board | ScoutingDirector, GeneralManager |
| GET | `/scouting/draft-boards/{id}/entries` | List board entries ordered by rank ascending; filter `active` | ScoutingDirector, GeneralManager |
| POST | `/scouting/draft-boards/{id}/entries` | Add a BOARD_READY, non-EXCLUDED prospect to an OPEN board; computes fit score and reranks | ScoutingDirector |
| POST | `/scouting/draft-boards/{id}/entries/reorder` | Manually move an active entry to `new_rank`; OCC-guarded on board version | ScoutingDirector |
| POST | `/scouting/draft-boards/{id}/freeze` | Freeze an OPEN board | ScoutingDirector |
| POST | `/scouting/draft-boards/{id}/unfreeze` | Reopen a FROZEN board | ScoutingDirector |
| POST | `/scouting/draft-boards/{id}/finalize` | Finalize a FROZEN board with at least one active entry | ScoutingDirector |
| POST | `/scouting/roster-needs` | Declare a roster need for a season | GeneralManager |
| GET | `/scouting/roster-needs` | List roster needs; filters `season_year`, `position`, `status` | GeneralManager, ScoutingDirector, AreaScout, MedicalStaff |
| GET | `/scouting/roster-needs/{id}` | Fetch one roster need | GeneralManager, ScoutingDirector, AreaScout, MedicalStaff |
| POST | `/scouting/roster-needs/{id}/close` | Close an OPEN roster need | GeneralManager |
| POST | `/scouting/free-agent-targets` | Add a free-agency target; annual cap hit computed at creation | GeneralManager |
| GET | `/scouting/free-agent-targets` | List free-agency targets; filters `status`, `position`, `season_year` | GeneralManager, ScoutingDirector |
| GET | `/scouting/free-agent-targets/{id}` | Fetch one free-agency target | GeneralManager, ScoutingDirector |
| POST | `/scouting/free-agent-targets/{id}/advance` | Advance target pipeline to `EVALUATING`, `APPROVED`, or `OFFERED`; APPROVED requires an OPEN matching RosterNeed | GeneralManager |
| POST | `/scouting/free-agent-targets/{id}/sign` | Sign an OFFERED target against a budget; fiscal gate on available | GeneralManager |
| POST | `/scouting/free-agent-targets/{id}/release` | Release a SIGNED target; restores budget commitment | GeneralManager |
| POST | `/scouting/free-agent-targets/{id}/pass` | Pass on a non-terminal target | GeneralManager |
| POST | `/scouting/budgets` | Create a season budget | GeneralManager |
| GET | `/scouting/budgets/{id}` | Fetch one budget | GeneralManager, ScoutingDirector |
| POST | `/scouting/budgets/{id}/adjustments` | Adjust rollover by a signed delta; OCC-guarded on budget version | GeneralManager |
| POST | `/scouting/prospects/{id}/interviews` | Schedule an interview; blocked by open flag review and half-open overlap | AreaScout, ScoutingDirector |
| POST | `/scouting/interviews/{id}/cancel` | Cancel a SCHEDULED interview, freeing the calendar slot | AreaScout, ScoutingDirector |
| GET | `/scouting/prospects/{id}/interviews` | List interviews of a prospect; filter `status` | GeneralManager, ScoutingDirector, AreaScout, MedicalStaff |
| POST | `/scouting/facilities` | Register a facility | GeneralManager |
| GET | `/scouting/facilities/{id}` | Fetch one facility | GeneralManager, ScoutingDirector |
| POST | `/scouting/facilities/{id}/bookings` | Book a facility; 30-minute buffer against existing bookings on the same facility | GeneralManager, ScoutingDirector |
| GET | `/scouting/facilities/{id}/bookings` | List bookings of a facility | GeneralManager, ScoutingDirector |
| POST | `/scouting/prospects/{id}/outcomes` | Record a post-draft outcome season for a DRAFTED prospect | GeneralManager |
| GET | `/scouting/prospects/{id}/outcomes` | List outcome records of a prospect | GeneralManager, ScoutingDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_REPORT_NOT_OWNED` | 403 |
| `ERR_FLAG_ACCESS_DENIED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_BOARD_NOT_OPEN` | 409 |
| `ERR_BOARD_EMPTY` | 409 |
| `ERR_TARGET_NOT_OFFERED` | 409 |
| `ERR_PROSPECT_NOT_BOARD_READY` | 409 |
| `ERR_PROSPECT_EXCLUDED` | 409 |
| `ERR_NO_ROSTER_NEED` | 409 |
| `ERR_OUTCOME_NOT_DRAFTED` | 409 |
| `ERR_FLAG_REVIEW_OPEN` | 409 |
| `ERR_DUPLICATE_REPORT` | 409 |
| `ERR_RANK_OUT_OF_BOUNDS` | 422 |
| `ERR_GRADE_OUT_OF_RANGE` | 422 |
| `ERR_WEIGHT_INVALID` | 422 |
| `ERR_INTERVIEW_OVERLAP` | 409 |
| `ERR_FACILITY_BUFFER_CONFLICT` | 409 |
| `ERR_BUDGET_EXCEEDED` | 422 |
| `ERR_STALE_VERSION` | 412 |
