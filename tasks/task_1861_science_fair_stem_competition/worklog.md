# Worklog — task_1861_science_fair_stem_competition

## Step 1: Create task directory — 2026-08-14T21:19:00.000Z

Pre-created by caller: `tasks/task_1861_science_fair_stem_competition/` + `workspace/`. Orchestrator did not scan tasks/ or compute an index.

## Step 2: Generate scaffold — 2026-08-14T21:56:39.000Z

Done. All three scaffold artifacts are generated and lint-clean.

## Report

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1861_science_fair_stem_competition/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` key, 9 rules × 2 instances = 18
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` key, 36 active instances + 2 `excluded_because` stubs across all 9 claim-extraction-guide sections

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Coverage: 60 endpoints, 13 entities, 18 §1.8 instances, 36 §1.9 instances, 779 calls scanned.

**Design (harder-than-expert calibration):**
- **Archetype**: quota/allocation (advancement slots + scholarship waterfall) blended with compliance/audit (ethics committee with segregation-of-duties, version-pinned approvals); flat FK topology, compound + parallel state dimensions, immediate consistency.
- **Hardest mechanics**: (1) dual-variant score normalization — per-judge Z_SCORE vs MIN_MAX with full-pool re-derivation on every submission (a sheet's normalized value drifts 0.000 → 1.000 when its judge scores *another* project); (2) pinned rounding order (normalize per-sheet at 3dp, then mean, then 2dp) with quorum threshold `ceil(max_judges × pct/100)` boundary instances (66%→2 sheets vs 67%→3 on max=3); (3) advancement waterfall with 4-key tie-break (aggregate DESC, median-raw DESC with even-count convention, sheet-count DESC, created_at ASC — never id), per-category waitlist depth `max(1, floor(slots/2))`, and cross-category at-large slot fallback; (4) scholarship waterfall with fixed tier precedence and integer-cents clamping (GRAND 400000 → FIRST clamped 300000→150000 → SECOND 0 on a 550000 pool); (5) mentor recognition dual variants (STRICT drives tier, INCLUSIVE drives leaderboard; 9 vs 13 points on identical outcomes, tier stays NONE at STRICT 9); (6) ResearchPlan revision cycle (DRAFT→SUBMITTED→UNDER_REVIEW→REVISION_REQUIRED→DRAFT) with `review_cycle_count` and approval version-pinning; (7) three OCC concurrency rules (edition publish, quota PATCH, project reassignment) all keyed on `expected_*_version`; (8) parallel Project dimensions (registration × ethics × inspection × judging) where a FAILed inspection withdraws the project but leaves judging rows intact.
- **All assertion numerics were pre-computed in Python** (z-scores, min-max values, aggregates 1.53/-1.29/0.32/-0.89, waterfall cents, recognition points/tiers) and written as literals.
- Every FK has a reverse-reachability GET; every error code is referenced by a validation/transition and exercised by at least one instance; the logical-clock test endpoint pins the mandatory `2026-08-01T00:00:00Z` startup default.

**Notable self-consistency fixes during the audit pass**: reattached the `combinatorial_formula` rule block after a splice, rerouted `ERR_ADVANCEMENT_FROZEN` from unreachable score-sheet guards to the quota-PATCH path, made auto-confirm happen only in the close-registration sweep (so the project-OCC corner instance's retry stays legal), and gave `Category.status` a producer (LOCKED at close-registration).

## Step 3: Copy shared files — 2026-08-14T21:57:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1861_science_fair_stem_competition/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T22:00:00.000Z

All verifications pass. The PRD is complete and shipped.

**Output written:** `/home/ubuntu/github/CodingPRD/tasks/task_1861_science_fair_stem_competition/workspace/PRD.md`

**Document structure** (designed from the domain, not copied from the example):
- §1 Introduction (2 paragraphs — pain-point angle)
- §2 Global Specifications, 10 subsections: RBAC, verbatim API Response Structure, Pagination, Common Resource Properties, The Logical Clock, Numeric Precision and Rounding, Optimistic Concurrency Control, Validation Pipeline and Priority Ordering, Nested Resource Retrieval, Edition Phases and Cross-Entity Cascades
- §3 Business Logic, 8 subsections organized along the season timeline (edition/categories → registration → ethics → judges/assignment → scoring/normalization → booths/inspection → advancement waterfall → awards/scholarships/mentor recognition)
- §4 Endpoint table (60 rows, 4 columns, RBAC verified against scaffold)
- §5 Error catalogue (26 rows, 2 columns, statuses verified)

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 57 required, 57 present, 0 missing
- endpoints[].request_body/input: 45 required, 45 present, 0 missing
- endpoints[].path_params: 1 required, 1 present, 0 missing
- common fields (id/created_at/updated_at/version): 4 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 10 checked, 10 expressed in §2.8 ordered-pipeline prose (incl. priority-6-before-7 note for booth scheduling), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write capability + expected_fair_edition_version/expected_project_version + ERR_STALE_VERSION + HTTP 412 each), 0 missing
- state_machines[].transitions: 26 checked, 26 fully expressed (preconditions paired with error ids, all side effects incl. cascades), 0 missing
- calculations[]: 6 checked, 6 fully expressed (both normalization variants, aggregate quorum/rounding order, advancement waterfall with at-large fallback, scholarship caps 400000/300000/150000/100000, mentor recognition strict+inclusive, judge selector eligibility/ranking), 0 missing
- validations[] conditions: 10 checked, 10 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 21 side-effect-bearing endpoints + 15 applies_to scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 57 checked, 57 reconstructible from prose (defaults, nullability, initial values, common_fields=false for JudgeConflict/ScoreSheet stated explicitly), 0 missing
- sibling-branch symmetry: 8 groups checked (3-way ethics decisions, PASS/FAIL, recuse/release, DRAFT/SUBMITTED withdraw, Z_SCORE/MIN_MAX, strict/inclusive recognition, explicit/auto assign, 4 award caps), 8 with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 386
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Additional precision checks (all pass):** §2.2 matches the canonical verbatim block byte-for-byte; no fuzzy/approximating words anywhere; no race-condition framing in OCC prose; all 26 error IDs appear in §2/§3 narrative near their triggers; all 28 state names, 55 enum values, and 7 role names appear backticked; every role's `identity:` translated in §2.1 (Mentor/Judge entity-backed, others opaque). The withheld difficulty/corner design files were never opened.

## Step 5: Generate unit tests — 2026-08-14T22:40:00.000Z

All verification gates pass. Final state of the deliverables:

## Summary

**Generated for task_1861_science_fair_stem_competition:**

### `test_helpers/` (9 files)
- `types.py` — 20 enums + 13 entity TypedDicts; `JudgeConflict`/`ScoreSheet` correctly omit `updated_at`/`version` per PRD §2.4 immutable-record rule
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (66 methods incl. inherited)
- `api_errors.py` — all 26 `ApiErrorId`s with HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity validators + immutable-record checker + pool-conservation invariant
- `factories.py`, `constants.py` — payload builders; waterfall caps, recognition points, tier thresholds, logical-clock/window constants
- `test_users.py` — shared headers for the four opaque roles + mandatory `make_mentor_headers`/`make_judge_headers` builders for the two entity-backed roles
- `fixtures.py` — composite builders (`setup_open_edition`, `setup_registration_closed`, `setup_judging`, `setup_publishable`, `setup_partially_judged`, `setup_project_with_plan`, `setup_plan_under_review`, `drive_revision_loop`, `judge_project_fully`, `publish_advancement` with OCC version read, etc.)

### `test_suite/` (conftest + 5 files, 72 tests)
- `test_01_edition_registration.py` (15) · `test_02_ethics_research_plans.py` (13) · `test_03_booths_inspections.py` (12) · `test_04_judging_scoring.py` (17) · `test_05_advancement_awards.py` (15)

### Audit results
- **Coverage:** all 18 difficulty instances have exactly 2 tests; all 36 non-stub corner instances have exactly 1; both `excluded_because` stubs skipped with cross-references verified to resolve
- **Tags:** all 72 tests carry exactly one verbatim `Design: Difficulty/...` or `Design: Corner/...` line; every tag resolves to a real instance with matching rule_id/section
- **Citations:** all 92 rule-bearing quotes verified verbatim against PRD.md (whitespace-normalized grep)
- **Hygiene:** no skip/skipif/xfail, no scaffold references, pyflakes clean, `pytest --collect-only` yields 72

### Key PRD-adjudication decisions
1. **`fair_edition_creation_defaults`**: dropped the `version == 1` assertion — PRD §2.4 says version increments by 1 per mutation but never fixes the initial value (two readers could start at 0 or 1); kept the PRD-verbatim `SETUP` + `advancement_freeze false` assertions.
2. **`score_submission_idempotency_double_submit`**: used `validate_error_is_one_of([ERR_INVALID_STATE, ERR_ALREADY_TERMINAL])` + 409 — PRD §2.8's terminal-source rule names only projects/awards/editions while §3.5 calls `SUBMITTED` terminal for assignments, so a single-error assertion is not uniquely derivable.
3. **Fixture ordering**: judges are recruited and activated while the edition is `REGISTRATION_CLOSED`, before `begin-judging` — the design recipes' order (activate during JUDGING) contradicts PRD §3.4 ("allowed while the edition is in `SETUP`, `REGISTRATION_OPEN`, or `REGISTRATION_CLOSED`"), so the PRD won.
4. All computed expectations (z-score/min-max aggregates, waterfall ranks/amounts, quorum boundary values, recognition points/tiers) were independently recomputed and match the design indices.

## Step 6: Generate implementation — 2026-08-14T22:40:00.000Z

The implementation is complete and verified.

## Summary

Generated a complete Python + Flask implementation of the Science Fair & STEM Competition API at `/home/ubuntu/github/CodingPRD/tasks/task_1861_science_fair_stem_competition/workspace/implementation/`.

**Structure:**
- `start.sh` — foreground launcher with guarded dependency install (`if ! python3 -c "import flask"`), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `app.py` — Flask entry point, blueprint registration, envelope-compliant error handlers
- `db.py` — in-memory stores (empty at boot, zero seeding) + logical clock pinned to `2026-08-01T00:00:00Z` at startup, advanced only via the FairDirector `_clock/set_current_utc` endpoint
- `errors.py` — full error catalog with exact IDs and HTTP statuses from scaffold Table 6
- `response.py` — envelope helpers producing exactly `{meta:{api_request_id, api_request_timestamp}, response_type, data}`, with `limit/offset/total_count/has_more` in meta for lists
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, six declared roles, entity-backed ownership for Mentor/Judge
- `validators.py`, `pagination.py`, `serializers.py` — priority-0 shape validation, `created_at`-ASC list pagination (limit default 10, 1..100), per-entity output shapes (JudgeConflict/ScoreSheet carry only `id`+`created_at`, no `updated_at`/`version`)
- `routes/` — one module per resource group covering all 41 endpoints: clock, fair-editions (full phase ladder with sweep cascades), categories (OCC + freeze gate), mentors, projects (OCC PATCH, submit/withdraw), research-plans (revision loop, decisions with SoD + rationale guards, REJECT cascade), judges (activate/deactivate, conflicts), judging (explicit + auto-selector assignment, score sheets, recuse/release), booths (window + uniqueness priority ordering, inspection PASS/FAIL cascade), awards + scholarship-pools
- `services/calculations.py` — Decimal-based math: Z_SCORE (population SD, sd=0 → 0.000) and MIN_MAX (tie → 0.500) normalization at 3dp ROUND_HALF_UP with full pool re-derivation per submission; project aggregates at 2dp with quorum `ceil(max_judges*pct/100)`; advancement waterfall (final_aggregate DESC → median-raw DESC → sheet-count DESC → created_at ASC, waitlist depth `max(1, slots//2)`, at-large slot fallback); scholarship waterfall (GRAND_PRIZE 400000 → CATEGORY_FIRST 300000 → CATEGORY_SECOND 150000 → SPECIAL_TOPIC 100000, min(cap, remaining), zero-amount conferrals); mentor recognition STRICT vs INCLUSIVE variants with tier thresholds 10/25/50

**Key correctness findings handled:**
- Pool re-normalization on each submission mutates other projects' sheets, so aggregates recompute for every affected project, not just the just-scored one
- `approved_plan_version` pins after the transition's own version increment, so the snapshot matches the plan's version at APPROVED time
- OCC on all three declared writes (publish-advancement, category PATCH, project PATCH) with `ERR_STALE_VERSION` 412
- Error priority ordering observed: shape (400) → auth (401) → RBAC (403) → not-found (404) → state with `ERR_ALREADY_TERMINAL` precedence → SoD (422) → temporal (inverted window beats booth-taken) → capacity/constraint → referential → fiscal

**Verification:** five smoke suites run against `start.sh` boots pass end-to-end — full season lifecycle for both normalization variants with hand-verified math, at-large promotion, freeze/terminal guards, recuse/release with conflict auto-creation, revision loop with review-cycle counting, FAIL-inspection cascade, and fresh-boot empty-store + default-clock confirmation.

## Step 7: Test-fix iteration loop — 2026-08-14T23:20:00.000Z

**Iteration 1 sweep (8 parallel rounds, per-test-server isolation):** 71/72 in every round. Union failure set across all 8 rounds = exactly one deterministic failure: `test_01_edition_registration.py::TestProjectTransitionGuards::test_submit_confirmed_project_rejected` (`assert 'SUBMITTED' == 'CONFIRMED'`).

**Diagnosis (per protocol):**
- STEP 1a/1b: PRD covers the rule verbatim — §3.2 "Submitting moves a project `DRAFT` → `SUBMITTED`" + §2.8 priority 4 "The target resource is in a state from which the requested transition is allowed; otherwise `ERR_INVALID_STATE` (409)". CONFIRMED is not in the terminal-source list, so ERR_INVALID_STATE is uniquely derivable. Test stays.
- STEP 2: TEST IS WRONG — fixture bug in `test_helpers/fixtures.py::setup_registration_closed`. The fixture's docstring promises projects "CONFIRMED after the closing sweep" (PRD §3.2 closing sweep: SUBMITTED + ethics NOT_REQUIRED → CONFIRMED), but it returned project snapshots read *before* `close_registration` ran, so callers received stale `SUBMITTED` readbacks.
- Fix: re-read each project via `get_project` after `close_registration` inside `setup_registration_closed`. All other call sites use only `project["id"]`, so the change is safe suite-wide.

**Iteration 2 sweep (foreground, 8 parallel rounds):** 72/72 in all 8 rounds — clean exit.

**Subagent's returned exit summary (verbatim):**

All 8 rounds of the final sweep report `passed == total` (72/72 each). Exiting with the Summary block.

## Summary

- **Iterations run:** 2 (sweep 1: 71/72 in all 8 rounds → fix → sweep 2: 72/72 in all 8 rounds, run foreground/blocking).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1861_science_fair_stem_competition/test_helpers/fixtures.py` — fixture `setup_registration_closed`: re-read each project via `get_project()` *after* `close_registration()` instead of returning pre-sweep snapshots. Why: the fixture's documented contract ("projects CONFIRMED after the closing sweep", per PRD §3.2's sweep `SUBMITTED` → `CONFIRMED`) was violated by the stale pre-close readbacks; every caller except one used only `project["id"]`, and the one status-asserting caller was correct to expect `CONFIRMED`.

- **Fixes applied to `test_suite/`:** none. The failing test `test_submit_confirmed_project_rejected` was faithful to PRD (§3.2 "Submitting moves a project `DRAFT` → `SUBMITTED`" + §2.8 priority-4 `ERR_INVALID_STATE`; CONFIRMED is not a terminal source, so the error is uniquely derivable) — the bug was upstream in the fixture.

- **Fixes applied to `implementation/`:** none. The implementation's submit path already enforced the state gate correctly; the failure was purely the test fixture's stale snapshot.

- **Final state:** all 8 parallel rounds pass 72/72 under `--isolation per-test-server`. Worklog updated at `/home/ubuntu/github/CodingPRD/tasks/task_1861_science_fair_stem_competition/worklog.md`.

## Step 8: Finalize PRD — 2026-08-14T23:35:00.000Z

`PRD_FINALIZED.md` has been produced at `/home/ubuntu/github/CodingPRD/tasks/task_1861_science_fair_stem_competition/workspace/PRD_FINALIZED.md` as an **exact copy of PRD.md — zero edits**.

## Summary

**Line counts / %-delta:** PRD.md = 306 lines; PRD_FINALIZED.md = 306 lines; delta = 0 lines, 0.0%.

**Changes:** none.

**Reasoning — why zero edits is the correct outcome here:**

The `<step_7_diff>` contains exactly one fix, and it is a pure fixture bug:

- The only change was to `test_helpers/fixtures.py` (`setup_registration_closed`, fixtures.py:296–333): re-read each project via `get_project()` after `close_registration()` instead of returning pre-sweep snapshots. No `implementation/` changes, no `test_suite/` changes, no deleted tests.

Verification that the behavior the fixture now relies on was already uniquely determined by the PRD (i.e., no PRD silence, no PRD/impl mismatch):

1. **Sweep semantics (fixture's contract "projects CONFIRMED after the closing sweep")** — PRD.md §3.2 (line 148) already pins: "every project in `SUBMITTED` whose `ethics_status` is `APPROVED` or `NOT_REQUIRED` at that moment is confirmed (`SUBMITTED` → `CONFIRMED`)". Implementation `close_registration` (`implementation/routes/fair_editions.py:144–154`) does exactly this, including leaving `PENDING`-ethics projects in `SUBMITTED` and locking categories, matching PRD verbatim. The stale snapshot was the fixture's own bug — the PRD needed no pinning.
2. **Version bump on sweep-mutated projects (fixture comment "version bumped by the cascade")** — PRD.md §2.6 (line 126) already pins per-entity cascade mutation: "its own `updated_at` refreshed and its own `version` … incremented". Impl `_touch(p)` at fair_editions.py:149/153 conforms.
3. **`test_submit_confirmed_project_rejected` (the sweep-1 failure)** — PRD.md §3.2 (line 144) pins "Submitting moves a project `DRAFT` → `SUBMITTED`" (DRAFT is the only source), and §2.8 priority 4 (line 111) pins `ERR_INVALID_STATE` (409) for transitions from non-allowed, non-terminal sources — `CONFIRMED` is not in the terminal-source list, so the generic state error is uniquely derivable. Impl `submit_project` (`implementation/routes/projects.py:212–223`) enforces exactly this ordering (`ERR_ALREADY_TERMINAL` for `WITHDRAWN` → ownership → `ERR_INVALID_STATE` for non-`DRAFT`), consistent with PRD §3.2 line 146's terminal-precedence rule. The test was faithful; the impl was correct; the fixture's stale pre-sweep `SUBMITTED` snapshot was the sole defect.

**Per-edit pre-edit search log:** no edits were committed, so no per-edit searches were triggered. The global verification above (enumeration of the submit path, withdraw path, close-registration sweep, and the §2.8 priority rules across `implementation/routes/projects.py`, `implementation/routes/fair_editions.py`, and PRD §2.6/§2.8/§3.2) confirmed that every behavior touched by the Step 7 fixture fix is already uniquely determined by existing PRD prose — inserting anything would have restated pinned behavior and risked violating the no-new-mismatch rule.

## Step 9: Complete PRD — 2026-08-15T00:05:00.000Z

All edits are complete and coherent. Here is the final report.

## Summary

**Source vs. output:** `/home/ubuntu/github/CodingPRD/tasks/task_1861_science_fair_stem_competition/workspace/PRD_FINALIZED.md` (306 lines, 48,407 chars) → `PRD_COMPLETED.md` (307 lines, 54,488 chars; **+1 line, +6,081 chars**). All changes are inline inserts/revisions within existing paragraphs; no new sections.

**Counts:** 29 ambiguity-pins, 9 mismatch-revisions (38 changes total).

### Mismatch revisions (PRD described behavior impl does not exhibit)

- §2.5 — revise — mismatch — "advances the clock" → the set call accepts any parseable ISO 8601 instant and moves the clock unconditionally, including backward — `implementation/routes/clock.py:28`
- §2.8 P8 — revise — mismatch — referential guard's field/applicability list extended to `fair_edition_id` payloads and to category/judge/award/pool creation and ethics decisions — `implementation/routes/categories.py:48-51`, `judges.py:43-55`, `awards.py:39-46,135-138`, `research_plans.py:213-215`
- §3.2 — revise — mismatch — mentors are not edition-scoped: registration requires the category to belong to the named edition and the acting mentor id to resolve to a registered mentor — `implementation/routes/projects.py:58-69`
- §3.3 — revise — mismatch — "one active research plan" dropped: the API caps nothing, a project may carry several plans — `implementation/routes/research_plans.py:41-72`
- §3.4 — revise — mismatch — activation gates only the auto-selector; explicit assignment and score submission do not re-check judge status (was "become scoreable only when activated") — `implementation/routes/judging.py:147,208-252`
- §3.4 — revise — mismatch — conflict declaration enforces no uniqueness on the judge–project pair (was "keyed by the pair") — `implementation/routes/judges.py:167-176`
- §3.4 — revise — mismatch — explicit-mode assignment pipeline order is: same-edition screen (ERR_REFERENTIAL_INTEGRITY) → SoD → capacity/duplication → dangling-judge existence — `implementation/routes/judging.py:89-117`
- §3.5 — revise — mismatch — provisional is recomputed from the full pool at completion so it coincides with the final (was "deliberately left unchanged as the historical snapshot") — `implementation/services/calculations.py:91-101`
- §3.8 — revise — mismatch — "any later award revocation" confinement: revocation is phase-gated to JUDGING/ADVANCEMENT_PUBLISHED, i.e. only before finalization — `implementation/routes/awards.py:106-111`

### Ambiguity pins (PRD silent → pinned to impl)

- §2.2 — insert — unrouted path/unsupported method → `ERR_NOT_FOUND` (404); non-JSON/non-object body → `ERR_INVALID_REQUEST` (400); unexpected fault → `ERR_INTERNAL` (500) in the same envelope — `implementation/app.py:39-54`
- §2.3 — insert — non-integer/out-of-range `limit`, non-integer/negative `offset` → `ERR_INVALID_REQUEST` (400) — `implementation/pagination.py:10-34`
- §2.3 — insert — list sort ties on identical `created_at` break on ascending `id` — `implementation/pagination.py:40`
- §2.4 — insert — `version` starts at 1 on creation — `implementation/routes/fair_editions.py:66` (and all other creates)
- §2.5 — insert — `created_at`/`updated_at` and `api_request_timestamp` are also rendered from the logical clock — `implementation/db.py:52-58`, `response.py:15-19`
- §2.5 — insert — unparseable `to_iso8601` → `ERR_INVALID_REQUEST` (400) — `implementation/routes/clock.py:22-26`
- §2.7 — insert — OCC version check position: after the phase check and before the all-judged sweep on publish; after freeze/phase guards on category update; after terminal/ownership/registration gates and before the category reference check on project update — `implementation/routes/fair_editions.py:196-211`, `categories.py:116-128`, `projects.py:174-194`
- §2.8 P0 — insert — `raw_score` outside 0–100 added to priority-0 range violations — `implementation/routes/judging.py:212-214`
- §3.1 — insert — category creation is not phase-gated; only edition existence is required — `implementation/routes/categories.py:31-51`
- §3.1 — insert — `advancement_freeze` once true is never cleared (even by archival), so a category update on an ARCHIVED edition reports `ERR_ADVANCEMENT_FROZEN` ahead of phase/version checks — `implementation/routes/categories.py:116-122`
- §3.2 — insert — on registration the reference checks run ahead of the edition-phase and category-status state checks — `implementation/routes/projects.py:57-79`
- §3.2 — insert — no field-level role split on project update: the owning mentor may reassign `category_id` exactly as the FairDirector — `implementation/routes/projects.py:143-203`
- §3.2 — insert — on submit/withdraw/update the WITHDRAWN terminal check fires ahead of the ownership check — `implementation/routes/projects.py:159-166,212-217,261-265`
- §3.3 — insert — plan creation is permitted whatever the project's registration state — `implementation/routes/research_plans.py:41-72`
- §3.3 — insert — after the SoD and rationale guards, `reviewer_mentor_id` must resolve to a registered mentor (`ERR_REFERENTIAL_INTEGRITY`) — `implementation/routes/research_plans.py:213-215`
- §3.3 — insert — `approved_plan_version` pins the plan's version as it stands after the approval transition's own increment (equals `version` at approval time) — `implementation/routes/research_plans.py:233-239`
- §3.3 — insert — a save leaving `plan_text` unchanged (including risk-level-only edits) keeps the plan in `REVISION_REQUIRED`; edits allowed regardless of project state; terminal-plan edits → `ERR_ALREADY_TERMINAL` — `implementation/routes/research_plans.py:113-128`
- §3.4 — insert — auto-selector final tiebreak: judges created at the same instant order by `id` ascending — `implementation/routes/judging.py:164-169`
- §3.5 — insert — score submission checks ownership first, ahead of the assignment terminal and phase checks — `implementation/routes/judging.py:224-248`
- §3.5 — insert — pool re-derivation recomputes aggregates and increments `version` for every project with a sheet in the judge's pool, not just the newly scored one — `implementation/routes/judging.py:279-285`
- §3.5 — insert — over-subscription: submitted count beyond `max_judges_per_project` clears `final_aggregate` back to null while provisional keeps recomputing; the `JUDGED` flip is one-way — `implementation/services/calculations.py:98-103`, `judging.py:288-293`
- §3.5 — insert — recusal carries no edition-phase gate, ownership precedes the terminal check, the auto-created conflict's `reason` is "recused", and any trigger aimed at a terminal assignment (score/recuse/release) → `ERR_ALREADY_TERMINAL` (409) — `implementation/routes/judging.py:229-231,302-390`
- §3.6 — insert — FAIL cascade touches `registration_status` only (judging/aggregates untouched); `PASSED`/`FAILED` terminal → `ERR_ALREADY_TERMINAL`; the result endpoint returns the updated project object — `implementation/routes/booths.py:132-163`
- §3.7 — insert — null `final_aggregate` sorts below every scored value in the ranking — `implementation/services/calculations.py:157`
- §3.7 — insert — at-large promotion changes only `advancement_result` (rank kept); every eligible project is mutated once, a promoted waitlister twice (version +2) — `implementation/services/calculations.py:174-196`
- §3.8 — insert — award proposal payload pins `fair_edition_id` + in-edition `project_id` (referential), with no edition-phase or project-state gate — `implementation/routes/awards.py:29-61`
- §3.8 — insert — a second scholarship pool for the same edition → `ERR_INVALID_STATE` (409) — `implementation/routes/awards.py:140-144`
- §3.8 — insert — within a scholarship tier, a null `final_aggregate` sorts below every scored value — `implementation/services/calculations.py:236-240`
- §4 — insert — filters are exact-match (no-match → empty page); the sole exception is the editions `status` filter, which validates its value (`ERR_INVALID_REQUEST` on unrecognized status) — `implementation/routes/fair_editions.py:78-81`

Notable cross-reference: the single weakened test assertion (`test_double_score_submission_rejected` accepting either 409 error) corresponds to impl's definite `ERR_ALREADY_TERMINAL` for terminal assignments, now pinned in §3.5.
