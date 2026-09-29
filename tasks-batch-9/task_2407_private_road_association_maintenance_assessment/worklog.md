# Worklog — task_2407_private_road_association_maintenance_assessment

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2407_private_road_association_maintenance_assessment/` and `workspace/` via `mkdir -p`. Directory name was pre-allocated by the caller (no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T10:52:21.000Z

All three artifacts are complete and the linter is clean.

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.

Files (all in `/home/ubuntu/github/CodingPRD/tasks/task_2407_private_road_association_maintenance_assessment/`):

- `SCAFFOLD.yaml` (2848 lines) — §1.0–§1.7 only, no design keys.
  - complexity_profile: `expert_plus`, archetypes multi_party_negotiation + pricing_engine, layers `[dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers, derived_field_reconciliation]`, topology `flat`, state-machine shape `cyclic`, role_model `segregation_of_duties`, consistency `immediate`.
  - 12 entities: Association, RoadSegment, Parcel (self-referential via subdivision), Member, AssessmentRoll, AssessmentCharge, SpecialAssessmentProposal, Ballot, MaintenanceProject, ContractorBid, DelinquencyAction, ConnectionRequest.
  - 10 state machines (roll DRAFT→CERTIFIED→LEVIED with a cyclic recall; proposal DRAFT↔BALLOTING with quorum-failure re-DRAFT; project solicitation↔award↔cancel; two-dimension member standing/access), 3 concurrency rules (bid-submit / ballot-cast / parcel-update OCC), 13 calculations, 56 validations (strict priority chain 1–56), 61 endpoints, 65 error codes, 6 roles (AssociationSecretary, AssessmentClerk, BoardTreasurer, RoadCommissioner, MemberOwner as `entity_backed:Member`, Contractor) with clerk-certifies/treasurer-levies and award/effectuate four-eyes separation.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2661 lines) — single key `scaffold_difficulty_design`: 9 rule groups, 21 depth instances (variant divergence on the frontage-vs-trip roll and statutory-vs-policy lien payoff, five-input emergency-access constraint propagation, cap/floor waterfall with negative residual, 4-hop cascades, priority-conflict pairs, exact-equality quorum/adoption boundaries, and four conservation invariants).
- `SCAFFOLD_CORNER_DESIGN.yaml` (4301 lines) — single key `scaffold_corner_design`: all nine sections, 81 instances = 56 full test recipes + 25 `excluded_because` stubs (every stub cites an existing §1.8 instance). Per section: entities 10, state_machines 12, calculations 11, validations 9, endpoints 6, errors 18 (every one of the 65 codes reachable or deferred), rbac 7 (ERR_FORBIDDEN_ROLE, ERR_NOT_RESOURCE_OWNER, ERR_SEGREGATION_OF_DUTIES, ERR_UNAUTHENTICATED), complexity_layers 7 (one full OCC instance per concurrency rule, all using `${var}` placeholders; the stale-project one proves OCC outranks the state guard), consistency_model 1.

Cross-file instance names are globally unique; all 1112 setup/trigger calls resolve against §1.5 endpoints, roles, inputs and captures. The only scaffold change needed for lint was adding four filtered collection reads (`GET /ballots`, `/contractor-bids`, `/delinquency-actions`, `/connection-requests`) since the linter only recognises sub-resource reverse-reachability when the parent path parameter is literally `{id}`.

## Step 3: Copy shared files — 2026-09-02T10:52:21.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2407_private_road_association_maintenance_assessment/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T11:08:25.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2407_private_road_association_maintenance_assessment/workspace/PRD.md`.

**Line count:** 485 lines. Document ends at §5; no audit footer or contract report inside the file.

**Section coverage**
- §1 Introduction — 3 paragraphs framing the association as a system of record and naming the two design commitments (pinned integer arithmetic, separated offices).
- §2 Global Specifications — 10 subsections, all domain-titled: 2.1 Identity, Roles, and the Separation of Association Offices; 2.2 API Response Structure (pasted verbatim from `section-2.2-response-structure.md`); 2.3 Pagination and List Ordering; 2.4 Record Identity, Audit Fields, and the Logical Clock; 2.5 Monetary Precision, Share Units, and Rounding Order; 2.6 Reserve Fund Accounting and Funding Posture; 2.7 The Emergency-Vehicle Access Standard; 2.8 Cascading Reconciliation and Derived-Field Consistency; 2.9 Optimistic Concurrency on Parent Records; 2.10 Request Validation Precedence and Path Resolution (all 56 priorities as an ordered list). None of the example PRD's subsection titles or its §3 shape were reused.
- §3 Business Logic — 8 subsections: association/road network setup, parcel enrollment–reclassification–subdivision, membership roll and deed verification, the annual roll (draft/certify/recall/levy plus the method-comparison what-if), special assessments and balloting, collections and delinquency remedies, contracting/bids/award/completion, and new-lot connections and easement disputes.
- §4 — 1 intro paragraph on 201-vs-200 (the 11 creating operations match the scaffold's `code: 201` set exactly) plus a 4-column table with all 61 endpoints.
- §5 — 2-column table with all 65 error IDs.

**Hard Contract audits (scripted against SCAFFOLD.yaml)**
- **Contract 1 — Field-Name Coverage: PASS.** 134 unique required identifiers (117 entity fields plus all `input`/`query_params` identifiers, optional-marker suffixes stripped); 0 missing from backticked prose. Spot-checked the method-comparison response fields, `current_utc`, `parent_parcel`, and `children` as well — all present.
- **Contract 2 — Rule Coverage: PASS.** All 41 state-machine transitions across the 10 machines are narrated with their triggers, preconditions and cascades (including the four-hop effectuation and connection-approval cascades, and the awarded-bid-withdrawal / cancel / inspection reserve reversions). All 13 calculations are rendered in prose with every named constant and every pinned rounding order and ranking tie-break. All 56 validation priorities appear in order with their `error_id`, HTTP status and `applies_to` scope; all 65 error IDs appear with statuses matching the scaffold (0 mismatches, 0 extras). Endpoint roles verified programmatically against `roles` for all 61 rows — 0 mismatches. Both dual-variant pairs (`FRONTAGE_WEIGHTED`/`TRIP_GENERATION_WEIGHTED`, `PER_PARCEL`/`ASSESSED_SHARE`, `STATUTORY`/`ASSOCIATION_POLICY`) are described symmetrically with their divergence stated.
- **Contract 3 — §3 Path Purity: PASS.** 857 backticked tokens in §3; 0 begin with `/`, 0 are bare HTTP methods, 0 combine method and path. No unbacked path fragments or method words appear anywhere in §3 either — endpoints are referenced only by state transition, role plus action verb, or capability description.

Also verified: no pseudocode operators or symbolic formulas anywhere in prose (all translated to words), no fuzzy quantifiers, no "simultaneously"/"first-writer-wins"/"race" framing in §2.9, and every markdown table row has exactly 4 or 2 columns. The two withheld design files were never opened.

## Step 6: Generate implementation — 2026-09-02T13:00:12.000Z

Boot verified and the implementation is complete. Worklog summary follows.

Note (resume run): a prior interrupted attempt had left a partial `workspace/implementation/` (calc.py, db.py, errors.py, response.py, validation.py — no app.py, no start.sh). The orchestrator deleted that fragment before relaunching Step 6 so the whole implementation would have single-agent provenance rather than a mix of two generators' partial module layouts.

**Root:** `workspace/implementation/`

### Files written (26 files, 3391 lines)

app.py 70, db.py 159, errors.py 87, middleware.py 61, response.py 79, validation.py 244, requirements.txt 1 (`Flask==3.0.3`), start.sh 10, services/__init__.py 1, services/constants.py 94, services/calc.py 189, services/state.py 467, routes/__init__.py 1, routes/associations.py 42, routes/road_segments.py 114, routes/parcels.py 164, routes/members.py 125, routes/assessment_rolls.py 237, routes/assessment_charges.py 95, routes/delinquency_actions.py 204, routes/proposals.py 211, routes/ballots.py 128, routes/projects.py 300, routes/contractor_bids.py 61, routes/connection_requests.py 228, routes/clock.py 19.

### Module layout
- **Infrastructure:** `db.py` (in-memory `Store` with the 12 entity dicts, logical clock pinned to `2026-08-01T00:00:00Z`, monotonic `_seq` insertion counter, id/timestamp/version helpers), `errors.py` (`ApiError` + full error-id → HTTP status table), `response.py` (envelope, `req_<20>` ids, 3-digit-fraction timestamps, Fraction→4dp display, pagination meta), `middleware.py` (`X-User-ID`/`X-User-Role` auth checks 1–3, 6 roles), `validation.py` (shape/type/enum/date validation = check 4, pagination bounds).
- **Domain services:** `services/constants.py` (all pinned constants and enums), `services/calc.py` (exact `Fraction` arithmetic, round-half-up cents, share units, the 8-step allocation waterfall with 50000-cent floor / 40% cap / single redistribution pass, vote thresholds, turnout requirement, access grading, connection fee + reserve buy-in, lien payoff, reserve draw/posture), `services/state.py` (cross-entity lookups, FK 404 resolution, member standing/access projections, reserve recomputation, tally recomputation, charge creation, award reversion, project cancellation cascades, lien-driven ballot voiding).
- **Routes:** 13 blueprints, one per resource family, registered in `app.py` with `strict_slashes=False` and envelope-emitting handlers for `ApiError`, `HTTPException` (404/405/400/415) and unexpected exceptions.

### Endpoint coverage
**61 / 61 endpoints implemented — exact match with the PRD §4 table** (30 GET, 30 POST, 1 PATCH). A programmatic diff of the PRD table against the registered `@bp.<method>` decorators reports zero missing and zero extra routes.

### Storage
In-memory Python dicts only. No SQLite, no JSON on disk, no `/tmp` cache; the only files the process ever wrote were `__pycache__` bytecode dirs, which have been removed. `db.Store()` starts completely empty — no seeding, preloading, or hardcoded entities; `GET /parcels` on a fresh boot returns `total_count: 0`.

### Boot verification
`PORT=8731 bash start.sh` (backgrounded) started cleanly (`Running on http://127.0.0.1:8731`) and answered:
- `POST /associations` → **201** with a full envelope (`response_type: "object"`, bare-UUID `id`, `version: 1`, `created_at: 2026-08-01T00:00:00.000Z`, `reserve_posture: "UNDERFUNDED"`).
- `GET /parcels?limit=5` → **200**, `data: []`, `meta.total_count: 0`, `has_more: false`.
- `GET /associations/nope` → **404** `ERR_ASSOCIATION_NOT_FOUND`.

The process was then killed, and a second fresh `start.sh` boot was run to simulate `--isolation per-test-server`: it became ready in ~4 s on this loaded host, served an empty store again, and was killed cleanly (port released). `start.sh` skips `pip install` when Flask already imports, so per-test relaunches don't contend on pip.

### Additional smoke run
A throwaway end-to-end script (`/tmp/smoke2407.py`, outside the repo) drove ~90 requests through every subsystem via the Flask test client and printed `SMOKE OK`: association → segment → 3 parcels/members with deed verification → roll certify/recall/re-certify/levy (residual 0, reserve contribution 600000) → method-comparison → payments and overpayment rejection → proposal open-balloting/ballots/OCC 412/tally ADOPTED with SPECIAL charges → project window conflict, 3 bids, segregation-of-duties 403, non-lowest 409, award, awarded-bid withdrawal with award reversion and reserve restore → DEFICIENT inspection cancelling a PAVING project → lien filing/effectuate (payoff 1647868), access restriction, release, payoff clearing standing → subdivision → connection request DISPUTED → resolve → APPROVED (fee 1208371, buy-in 332973, parent-billed CONNECTION_FEE charge) → DENIED branch → pagination/auth/envelope negative cases.

## Step 5: Generate unit tests — 2026-09-02T14:32:40.000Z

Stage 2 is complete. Queue A and queue B are both fully translated, and every audit passes.

### Files written

Stage 1 — `test_helpers/` (9 files, 2,530 lines): types.py 417, api_client.py 283, api_errors.py 144, assertions.py 406, constants.py 80, factories.py 238, fixtures.py 656, test_users.py 85, __init__.py 221.

Stage 2 — `test_suite/` (16 files, 9,672 lines, 198 test functions / 203 collected cases)

| file | lines | tests | instances |
|---|---|---|---|
| `conftest.py` | 60 | – | – |
| `test_01_assessment_roll_allocation.py` | 428 | 9 | 3 (A) |
| `test_02_emergency_access_standard.py` | 439 | 9 | 2 (A) |
| `test_03_delinquency_remedies.py` | 605 | 13 | 4 (A) |
| `test_04_special_assessment_balloting.py` | 753 | 14 | 5 (A) |
| `test_05_new_lot_connections.py` | 642 | 10 | 3 (A) |
| `test_06_contracting_and_reserve.py` | 674 | 12 | 4 (A) |
| `test_07_records_reads_and_rejections.py` | 531 | 10 | 10 (B entities) |
| `test_08_lifecycle_transitions.py` | 752 | 9 | 9 (B state_machines) |
| `test_09_share_units_and_money_arithmetic.py` | 625 | 12 | 6 (B calculations) |
| `test_10_validation_precedence.py` | 735 | 16 | 6 (B validations) |
| `test_11_endpoint_behaviours.py` | 655 | 14 | 6 (B endpoints) |
| `test_12_guard_code_reachability.py` | 673 | 17 | 4 (B errors) |
| `test_13_remedy_connection_and_funding_guards.py` | 808 | 18 | 4 (B errors) |
| `test_14_role_and_identity_boundaries.py` | 711 | 19 | 7 (B rbac) |
| `test_15_version_guards_and_immediate_visibility.py` | 579 | 16 | 3 (B complexity_layers) + 1 (B consistency_model) |

### Per-queue instance counts

- **Queue A (§1.8 depth index): 21 non-stub instances, 21 translated, 0 skipped.** 67 tests; every instance carries >=2 tests (range 2–5).
- **Queue B (§1.9 breadth index): 56 non-stub instances, 56 translated, 0 skipped.** 131 tests. Section coverage: entities 10/10, state_machines 9/9, calculations 6/6, validations 6/6, endpoints 6/6, errors 8/8, rbac 7/7, complexity_layers 3/3, consistency_model 1/1. The 25 `excluded_because:` stubs were deliberately not translated, per the design contract.

### Probe-level omission (one)

Inside `Corner/errors/roll_and_subdivision_guard_codes_are_each_reachable`, the design asks for a single-child subdivision to return `ERR_FRONTAGE_MISMATCH` (422). PRD §3.2 ("An array with fewer than two entries is a malformed request and is rejected as such") plus §2.10 item 4 uniquely derive `ERR_INVALID_REQUEST` (400) instead, so that one probe was omitted rather than asserting a PRD-contradicted outcome; the rest of the instance (the 200+80 frontage mismatch, the no-children-created check, the certify/re-certify guard, the empty-association guard) is translated across 4 tests.

### Coverage audit results

- **Design-tag audit:** 198 tests, 77 distinct design tags, **0 problems** — every test carries exactly one trailing `Design:` line, every tag resolves to a real non-stub instance name, no untagged or dual-tagged tests.
- **Instance-coverage diff against both yaml indices:** `CORNER non-stub: 56, stubs: 25, missing: []` / `DIFFICULTY non-stub: 21, stubs: 0, missing: []` — 77 tags emitted, exactly matching 21+56.
- **PRD-citation pass:** 293 docstring quotes, all found verbatim in `workspace/PRD.md` under whitespace-normalised grep, and all §-labels verified to fall inside the labelled section (one mislabel found and fixed: a reserve-posture quote labelled §2.3 that lives in §2.6).
- **Static checks:** `pyflakes test_suite/*.py test_helpers/*.py` clean; every module imports cleanly; `pytest --collect-only` collects 203 cases in 0.95 s (198 functions, two of them parametrised); zero occurrences of the word "scaffold" anywhere in `test_helpers/` or `test_suite/`.
- The suite was not executed against an implementation: `workspace/implementation/` was never read or written, per the isolation constraint.

## Step 7: Run tests and iterate — 2026-09-02T15:15:30.000Z

Fully green.

**Iterations run: 3** (each a parallel 8-round `per-test-server` sweep, 203 collected cases per round, run under `setsid nohup`).

- Sweep 1: 198/203 in all 8 rounds — 5 failures, identical in every round (no flakiness anywhere in the suite).
- Sweep 2: 202/203 in all 8 rounds — 1 remaining failure.
- Sweep 3: **203/203 in all 8 rounds** (346 s per round).

### Tests deleted
None. Two individual assertions were trimmed under STEP 1c (partial coverage); no test function was removed.

**Assertions removed for PRD silence:**
1. `test_05_new_lot_connections.py::TestConnectionFeeComponentRounding::test_each_component_is_rounded_before_the_four_are_added` — `assert approved["decided_at"] == "2026-10-01T00:00:00Z"`. **Category: format/serialization silence.** PRD §3.8 says only "stamps `decided_at` with the current logical-clock instant"; §2.4 mandates three fractional digits for `created_at` and `api_request_timestamp` *only*, while describing the clock as reading "exactly `2026-08-01T00:00:00Z`" — so PRD itself forces at least one field to diverge from the clock's bare-Z rendering without saying which. Replaced with an instant assertion (`startswith("2026-10-01T00:00:00")`), which keeps the covered part (the stamp is the clock instant) and drops the uncovered part (its fractional-digit rendering). Scaffold driver: `Difficulty/combinatorial_formula/connection_fee_round_per_component_versus_sum_then_round`.
2. `test_02_emergency_access_standard.py::TestDeficientInspectionCascade::test_deficient_regrade_cancels_the_paving_project_and_rejects_its_bid` — `assert project["awarded_amount_cents"] == 250_000` ("the awarded amount survives as the historical record"). **Category: branch-asymmetric side-effect silence.** PRD §3.7's withdrawal branch explicitly resets `awarded_bid_id`/`awarded_amount_cents`/`awarded_by_user_id`; the cancellation branch enumerates only status, bids→`REJECTED`, and the reserve-draw return, and opens with "Cancellation is the commissioner's version of **the same reversal**" — which a faithful reader can take either as "only the enumerated effects" (award amount survives) or as "the same reversal" (award fields cleared). No verbatim sentence states retention. Scaffold driver: `Difficulty/transitive_cascade/deficient_inspection_cancels_paving_reverses_reserve_and_retunes_threshold`.

### Fixes applied to `test_helpers/`
None — no fixture, factory, or role-header bug was found.

### Fixes applied to `test_suite/`
- `test_08_lifecycle_transitions.py::TestInitialStatesAndTerminalLockdown::test_a_paid_charge_refuses_both_payment_and_a_new_remedy` — expected status for `POST /assessment-charges/{id}/payments` changed 201 → 200. PRD §4 lists the eleven operations returning `201 Created` and payment is not among them ("Every other successful operation … returns `200 OK`"), so the test mis-translated the PRD.

### Fixes applied to `implementation/`
- `workspace/implementation/routes/road_segments.py`, `record_inspection()` — `last_inspection_at` now stores the supplied `inspected_at` string verbatim instead of re-rendering it with three fractional digits. PRD §3.1 verbatim: "`last_inspection_at` is set to the supplied `inspected_at`". This fixed 3 failing tests (2 in `test_02`, 1 in `test_11`) and is consistent with the already-passing `test_08` assertion that uses `startswith`. `V.req_dt` is still called so the field is shape-validated as ISO 8601.

No implementation check required by PRD was weakened, no endpoint/field/side-effect was added without a verbatim PRD sentence, storage remains in-memory dicts only (no seeding, no on-disk persistence), and runner `results.*.json` / `__pycache__` artifacts were cleared from `implementation/`.

## Step 7 (addendum): confirming sweep — 2026-09-02T15:35:00.000Z

The Step 7 subagent deleted its `results.*.json` after exiting; the orchestrator had already independently verified 203/203 in all 8 rounds of its final sweep before the deletion. To restore the artifact the pipeline's output spec requires, the orchestrator re-ran one full 8-round `setsid nohup` sweep (concurrently with Step 8, which only reads `implementation/`). Result: **203/203 in all 8 rounds again**, and `workspace/implementation/results.{1..8}.json` are on disk. Log: `workspace/sweep_confirm.log`.

## Step 8: Finalize PRD — 2026-09-02T15:36:20.000Z

`PRD_FINALIZED.md` written at `workspace/PRD_FINALIZED.md`.

## Line counts
- `PRD.md`: 484 lines
- `PRD_FINALIZED.md`: 486 lines — **+2 lines, +0.41%** (2 revised lines, 1 inserted paragraph)

## Changes

- **§2.4 — insert** — pinned the rendering of every server-written instant field to three fractional digits + trailing `Z` (so a clock-stamped instant reads `…T00:00:00.000Z`), enumerating `updated_at`, the nine clock-stamped fields, the three client-supplied instants the server re-renders, and `api_request_timestamp`; named `last_inspection_at` as the one verbatim-retained exception and excluded calendar-date fields — `implementation/db.py:56-68` (`iso`/`now_iso`).
- **§3.7 — revise** — cancellation now states that `awarded_bid_id`/`awarded_amount_cents`/`awarded_by_user_id` are cleared (not retained as a historical record), a no-op when cancelled from `BID_SOLICITATION` — `implementation/services/state.py:411-421`.
- **§3.1 — revise** — the deficient-inspection cascade explicitly clears each cancelled project's award fields "as §3.7's cancellation describes" (the cascade shares `cancel_project`) — `implementation/services/state.py:411-421`, called from `implementation/routes/road_segments.py:110`.

## Pre-edit search log

**Edit 1 (§2.4 timestamp rendering)**
- (a) Subject: how the server serialises instant-valued fields.
- (b) Enumerated/read: `db.py` (`iso`, `now_iso`, `date_str`, `INITIAL_CLOCK`), `response.py` (`_meta` → `api_request_timestamp`, `serialize`), and every `_at` write across `routes/` + `services/` via grep: `road_segments.py:98` (verbatim `inspected_at`), `projects.py:167` (`submitted_at`), `projects.py:274` (`completed_at` via `iso()`), `proposals.py:130-131` (`balloting_opened_at` via `now_iso`, `balloting_closes_at` via `iso()`), `proposals.py:207-208` (reset to null), `ballots.py:62` (`cast_at`), `members.py:92` (`deed_verified_at`), `assessment_rolls.py:171/228` (`certified_at`, `levied_at`), `delinquency_actions.py:150/186` and `state.py:442` (`effective_at`, `released_at`), `connection_requests.py:154/184` (`decided_at` on both DENIED and APPROVED paths), `clock.py:19` (`current_utc`), `db.py:128-144` (`new_row`/`touch`). Also grepped all date-only fields (`date_str` sites: `window_*_date`, `fy_*_date`, `due_date`, `delinquent_since`, `restriction_*_date`, `deed_recorded_date`) to make sure the sentence does not sweep them in.
- (c) Adjustment: scoped the claim to "instant-valued field**s**" and added the explicit "Calendar-date fields are unaffected: they remain plain `YYYY-MM-DD` dates" clause so the sentence cannot be read as forcing fractional digits onto date fields; carved out `last_inspection_at` explicitly (a bare universal would have contradicted `road_segments.py:98`); said "normalises from a client-supplied value" rather than naming only `completed_at`, so `balloting_closes_at` and `current_utc` are covered; deliberately left rounding-vs-truncation of sub-millisecond input unspecified (no path exercises it) rather than asserting a rule.

**Edit 2 (§3.7 cancellation award fields)**
- (a) Subject: lifecycle of `awarded_bid_id` / `awarded_amount_cents` / `awarded_by_user_id`.
- (b) Enumerated/read: `projects.py:75/80/83` (creation defaults null/0/null), `projects.py:246-251` (award sets all three), `state.py:411-421` `cancel_project` (clears all three + `reserve_draw_cents`; called from `projects.py:298` and `road_segments.py:110`), `state.py:424-432` `revert_award` (bid-withdrawal path, already stated in PRD), `projects.py:273-276` `complete_project` (does *not* touch award fields), `projects.py:114` (`awarded_bid_id` list filter), `state.py:300-302` (reserve reconciliation excludes `CANCELLED`).
- (c) Adjustment: scoped the sentence to the cancellation branch only, so completion's retention of the award figures is untouched; added the "no-op when cancelled straight out of `BID_SOLICITATION`" clause because `cancel_project` runs the same clear on a never-awarded project and a bare "returns to null/zero" could be read as implying a prior award.

**Edit 3 (§3.1 cascade award fields)**
- (a) Subject: same as Edit 2, on the inspection-cascade callsite.
- (b) Enumerated/read: `road_segments.py:101-113` (PAVING + `BID_SOLICITATION`/`AWARDED` filter, `S.cancel_project(project)` with no reason, single `recompute_reserve`), `state.py:411-421`, `state.py:404-408` `reject_active_bids`.
- (c) Adjustment: cross-referenced §3.7 instead of restating the field list, and did **not** mention `cancellation_reason` — the cascade passes no reason and leaves it null, so any restatement risked implying a reason is written here.

**Non-edits** (verified PRD already determines the behaviour):
- `test_08` payment `201 → 200`: §4 already enumerates the eleven `201 Created` operations and excludes payment. Test-side mis-translation, no PRD gap.
- `last_inspection_at` verbatim storage: §3.1 already says verbatim ("`last_inspection_at` is set to the supplied `inspected_at`"); the implementation was corrected to match, so the §3.1 prose stays untouched — Edit 1 only preserves it against the new §2.4 universal.

## Step 9: Complete PRD — 2026-09-02T15:45:10.000Z

`PRD_COMPLETED.md` is written. Summary:

**Counts**
- `PRD_FINALIZED.md`: 486 lines / 93,501 chars → `PRD_COMPLETED.md`: 486 lines / 98,528 chars (**+5,027 chars**, 0 line delta — all 29 edits are in-paragraph, spread over 27 lines; no new sections or paragraphs).
- **Ambiguity-pins: 26. Mismatch-revisions: 3.**

**Changes**
- §2.3 Pagination & List Ordering — insert — ambiguity — `created_at` ties break by write order (server insertion), not `id`; matters because the logical clock stands still — `db.py:147`
- §2.4/§2.8 Cascades — insert — ambiguity — a projection re-run landing on unchanged values is *not* a mutation: no `updated_at`/`version` bump (member dims, association reserve triple, DRAFT threshold) — `services/state.py:229,308,279`
- §2.5 Rounding — insert — ambiguity — `reserve_funding_ratio` rounds **half up** to 4dp — `services/calc.py:26`
- §2.9 Optimistic Concurrency — insert — ambiguity — every `expected_*_version` must be an integer >= 0 — `routes/parcels.py:78`, `routes/ballots.py:25`, `routes/projects.py:144`
- §3.1 Segment creation — revise — mismatch — `bridge_load_rating_tons` is null only when *omitted*; the server never nulls it because `bridge_present` is false — `routes/road_segments.py:29,44`
- §3.1 Access inspection — insert — ambiguity — measured width may be exactly 0; `bridge_load_rating_tons` overwritten only when the key is present (omit = retain, explicit null = clear) — `routes/road_segments.py:85-95`
- §3.1 Deficiency cascade — insert — ambiguity — cascade-cancelled projects keep `cancellation_reason` null — `services/state.py:411-416`
- §3.2 Subdivision — insert — ambiguity — each child's `frontage_feet` must be strictly > 0 — `routes/parcels.py:122`
- §3.4 Allocation step four — insert — ambiguity — clamp is floor-then-cap, so the cap wins when it falls below the 50,000-cent floor — `services/calc.py:73`
- §3.4 Recall — insert — ambiguity — `recall_reason` required non-empty, persisted nowhere — `routes/assessment_rolls.py:181`
- §3.4 Method comparison — insert — ambiguity — empty assessable set answers 200 with zero totals/divergences and each residual = full `budget_requirement_cents` — `routes/assessment_rolls.py:103,119`
- §3.4 Listings — insert — ambiguity — roll list filters `association_id`, `fiscal_year`, `status` — `routes/assessment_rolls.py:80-82`
- §3.5 Adoption — insert — ambiguity — empty restricted set still adopts, writing no charges (no `ERR_NO_ASSESSABLE_PARCELS`) — `routes/proposals.py:151`
- §3.5 Ballot cast — insert — ambiguity — `proposal_id` resolves before `member_id`; casting is never checked against the eligible voter set (parcel `status`/segment uncompared) — `routes/ballots.py:27-49`
- §3.5 Ballot listings — insert — ambiguity — per-proposal and per-member listings take a `status` filter — `routes/proposals.py:94`, `routes/members.py:101`
- §3.6 Payment — insert — ambiguity — `amount_cents` integer >= 0; zero accepted and inert — `routes/assessment_charges.py:56`
- §3.6 Remedy initiation — **revise** — **mismatch** — collectible set is `OPEN`/`DELINQUENT`/**`LIEN_ENCUMBERED`**, per §2.10 check 17, not just the first two — `routes/delinquency_actions.py:32`
- §3.6 Remedy initiation — insert — ambiguity — fiscal-containment test is `start >= fy_start_date` and `end <= fy_end_date`; restriction dates on `NOTICE`/`LIEN_FILING` are stored null even if supplied — `routes/delinquency_actions.py:53,65-66`
- §3.6 Release — insert — ambiguity — `release_reason` recorded on the `EFFECTIVE` branch too; charge leaves `LIEN_ENCUMBERED` only when no `EFFECTIVE` `LIEN_FILING`/`ACCESS_RESTRICTION` remains (an `EFFECTIVE` `NOTICE` never holds it) — `routes/delinquency_actions.py:187,191-198`
- §3.6 Remedy listings — **revise** — **mismatch** — the cross-cutting listing spans every charge in the store, not one association; per-charge takes `status` only — `routes/delinquency_actions.py:94`, `routes/assessment_charges.py:88`
- §3.7 Project creation — insert — ambiguity — `window_start_date` strictly before `window_end_date` → `ERR_INVALID_DATE_RANGE`, checked only after both window rules pass — `routes/projects.py:68`
- §3.7 Award — **revise** — **mismatch** — condition order corrected to segregation → solicitation → bid `SUBMITTED` → PAVING compliance → bond → `ERR_BID_PROJECT_MISMATCH` last (PRD prose had mismatch third and bond/compliance reversed) — `routes/projects.py:193-210`
- §3.7 Withdrawal — insert — ambiguity — `withdrawal_reason` required non-empty, persisted nowhere — `routes/contractor_bids.py:44`
- §3.7 Cancellation — insert — ambiguity — a `COMPLETE`/`CANCELLED` project is refused with `ERR_PROJECT_NOT_IN_SOLICITATION` — `routes/projects.py:294`
- §3.7 Completion — insert — ambiguity — `actual_cost_cents` required integer >= 0 — `routes/projects.py:262`
- §3.7 Bid listings — insert — ambiguity — per-project bid listing takes a `status` filter — `routes/projects.py:127`
- §3.8 Filing — insert — ambiguity — the `MemberOwner` ownership comparison is skipped when no qualifying parent member exists, so `ERR_PARENT_MEMBER_NOT_FOUND` wins over `ERR_NOT_RESOURCE_OWNER` — `routes/connection_requests.py:50-54`
- §3.8 Approval — insert — ambiguity — the `CONNECTION_FEE` charge's `share_units_snapshot` is the lot's recomputed `frontage_share_units` (regardless of `method_variant`), `proposal_id` null — `routes/connection_requests.py:200`
- §3.8 Listings — insert — ambiguity — the per-lot listing takes a `status` filter — `routes/connection_requests.py:105`

Nothing under `implementation/`, `test_suite/`, or `test_helpers/` was modified.
