# Worklog — task_1505_traffic_calming_request_neighborhood_speed

## Step 1: Create Task Directory — 2026-08-13T14:50:00.000Z

Pre-assigned by pipeline runner: `tasks/task_1505_traffic_calming_request_neighborhood_speed/` with `workspace/` already created. Treated as DONE per instructions; verified existence only.

## Step 2: Generate Scaffold — 2026-08-13T16:29:00.000Z

All three scaffold artifacts are generated, self-consistent, and lint-clean.

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_1505_traffic_calming_request_neighborhood_speed/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design` key (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design` key (§1.9)

**Lint verdict** (pasted verbatim from the final `scaffold_lint.py` run): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1,363 recipe calls scanned; 0 violations.)

**Entity set (12)**: StreetSegment, Resident, TrafficCalmingRequest, PetitionSignature, SpeedStudy (covers both INITIAL and POST_INSTALLATION/effectiveness studies), StudyObservation, FundingCycle, TreatmentPlan, Ballot, BallotVote, InstallationWorkOrder, RemovalRequest. Flat topology with FK links; Resident is entity-backed, the four staff roles opaque.

**State machines (7)**: TrafficCalmingRequest (20-stage pipeline with a WAITLISTED→RANKING_ELIGIBLE cycle-back loop and clock-sweep auto-transitions), SpeedStudy (COLLECTING⇄ANALYZED recollection cycle → CERTIFIED), TreatmentPlan (DRAFT→SUBMITTED→APPROVED with REVISION_REQUESTED→DRAFT revision cycle plus supersede-to-WITHDRAWN), Ballot (OPEN→TALLIED branching into CONSENT_GRANTED/CONSENT_DENIED forks), InstallationWorkOrder (parallel dimensions schedule_status × emergency_review_status), FundingCycle (OPEN⇄RANKING_PUBLISHED republish → CLOSED), RemovalRequest.

**Calculations (9)**: petition threshold (ceil 60%), study aggregation (provisional-all vs certified-valid input sets, round_half_up pinned), tiered 4-input criteria score with 60-point eligibility gate, citywide ranking waterfall (score/crash/created_at ordering, strict-stop rule, per-request contingency rounding pinned), plan-approval budget re-baseline, integer-ratio ballot tally (quorum + exact-60% boundary), half-open crew schedule conflict, 7-day buffer-inclusive study-window conflict, dual-variant effectiveness verdicts (p85-official vs mean-advisory).

**Endpoints**: 50 (incl. `POST /_clock/set_current_utc` with the mandatory `2026-08-01T00:00:00Z` startup default driving petition-deadline and ballot-tally sweeps). **Error catalog**: 44 codes. **Concurrency rules**: 2 OCC rules (plan-create supersede on request version; ranking republish on cycle version).

**Design instances**: 18 difficulty instances (2 per each of the 9 rules, all differentiators honored — e.g., dual-variant spans study-scoring vs budget domains; combinatorial modes (a) tiered and (b) rounding-order; cascades depth-3 approve-chain and depth-2 clock-sweep-chain; all numeric asserts pre-computed literals). 59 corner instances (51 active + 8 `excluded_because` stubs referencing §1.8). Names are unique across both files; all stub references resolve.

Notable design decisions made during self-review: five "one active X per request" uniqueness errors and the ballot/petition window errors were removed as untriggerable (masked by earlier state-priority gates or the atomic clock sweep), and plan creation was fixed to accept both FUNDED (first plan) and DESIGN_IN_PROGRESS (superseding plan) so the OCC supersede race is actually reachable.

## Step 3: Copy Shared Files — 2026-08-13T16:30:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1505_traffic_calming_request_neighborhood_speed/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T16:47:00.000Z

All checks pass. The "exactly sixty percent passes" spot-check miss is only a phrasing difference — the rule is present in §3.6 as "a slate standing at exactly sixty percent in favor passes". Work is complete.

## Summary

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_1505_traffic_calming_request_neighborhood_speed/workspace/PRD.md` (328 lines, ~7,500 words). The two forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

**Section list:**
- §1 Introduction (2 paragraphs, program-context angle)
- §2 Global Specifications: 2.1 User & Role-Based Access Control (all 5 roles with identity translations: Resident entity-backed, four opaque roles with their recorded fields) · 2.2 API Response Structure (**byte-identical** to the canonical source, diff-verified) · 2.3 Pagination · 2.4 The Program Logical Clock (startup default `2026-08-01T00:00:00Z`, both sweeps) · 2.5 Common Resource Properties (incl. the three immutable event records carrying only `id`/`created_at`) · 2.6 Measurement, Money & Rounding (integer cents, per-request contingency rounding, half-up rules) · 2.7 OCC (both guarded writes) · 2.8 Cross-Entity Consistency & Automatic Transitions · 2.9 Nested Resource Retrieval (all ten 404 ids, left-to-right) · 2.10 Validation Order of Precedence (nine tiers, explicitly ordered)
- §3 Business Logic (8 subsections): 3.1 Segments & Residents · 3.2 Request Filing & Petition · 3.3 Speed Studies (collection/analysis/certification, criteria score bands) · 3.4 Ranking & Funding Waterfall · 3.5 Treatment Design & Approval (3-link cascade, SoD) · 3.6 Consent Ballot (quorum, integer cross-multiplication tally, compensating release) · 3.7 Installation (dual status dimensions, half-open crew conflict, bubble-up) · 3.8 Effectiveness & Removal (dual verdicts 3.0/2.0 mph, 365-day gate)
- §4 Endpoint Definitions — 50 rows, exact method+path parity with scaffold; §5 Error Code Catalogue — 44 rows, all statuses matching scaffold

**Coverage self-audit (all three hard contracts PASS):**
- **Contract 1 (Field-Name Coverage): PASS** — entities[].fields: 81/81 present, 0 missing; endpoints[].input: 43/43 present, 0 missing; path params: 11/11 present (in §4 backticked paths), 0 missing
- **Contract 2 (Rule Coverage): PASS** — 9/9 validation priority tiers expressed with explicit ordering; 2/2 OCC rules (write endpoint + `expected_request_version`/`expected_funding_cycle_version` + `ERR_STALE_VERSION`/412, no race framing); 44/44 state-machine transitions fully expressed (from/to, preconditions paired to error ids, side effects); 9/9 calculations in precise reconstructible prose (inclusive boundaries, ceilings, per-request-before-summation rounding, strict-stop waterfall, adjacency-allowed crew rule, 7-day inclusive study buffer with 8th-day-free corollary, zero-votes denial); 44/44 error ids present in §1–§4 prose; all endpoint side effects and applies_to scopes expressed; field defaults/null-until semantics placed; sibling branches symmetric (approve/reject, granted/denied, funded/waitlisted, cleared/blocked, triple-source supersede)
- **Contract 3 (§3 Path Purity): PASS** — 413 backtick tokens scanned in §3; 0 path-prefixed, 0 bare HTTP methods, 0 method+path combos

Also verified: all 50 state/enum values and all 5 role names appear verbatim; no fuzzy quantifiers or pseudocode operators leaked into prose.

## Step 6: Generate Implementation — 2026-08-13T17:36:00.000Z

Subagent returned: "Imports cleanly. Now boot it on a free port and smoke-test." (final text; full implementation written before exit).

Orchestrator verification (implementation/ tree + boot smoke test):
- Files: app.py, auth.py, calc.py, envelope.py, errors.py, helpers.py, store.py, validate.py, requirements.txt, start.sh, routes/ (12 modules: clock_routes, segments, residents, requests, signatures, studies, plans, cycles, ballots, workorders, removals, __init__).
- 50 route registrations confirmed via grep, matching PRD §4 endpoint table (incl. POST /_clock/set_current_utc).
- Boot smoke test: `PORT=<free> bash start.sh` binds 0.0.0.0 in foreground; POST /api/segments (CityAdmin) → 201-style object envelope with server-minted UUID, version=1, created_at=2026-08-01T00:00:00.000Z (logical clock default per PRD §2.4); GET /api/segments/<id> roundtrips the same record. Error envelope shape verified on an undefined-method path (ERR_METHOD_NOT_ALLOWED with response_type=error + meta block).

## Step 5: Generate Unit Tests — 2026-08-13T17:58:00.000Z

Generation complete. Summary:

## Files written

**`test_helpers/`** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1505_traffic_calming_request_neighborhood_speed/test_helpers/`):
- `types.py` — 12 entity TypedDicts (event records `PetitionSignature`/`StudyObservation`/`BallotVote` correctly omit `updated_at`/`version`) + 12 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (42 methods, incl. `/_clock/set_current_utc`)
- `api_errors.py` — `ApiErrorId` (38 errors) + HTTP status map from PRD §5, registered with the framework via `set_error_http_status_map`
- `assertions.py` — per-entity asserts, `assert_cycle_budget_invariant`, and `assert_timestamp_equals` (parse-based, tolerant of fractional-digit formatting)
- `factories.py` — 13 payload factories, input fields only
- `constants.py` — PRD thresholds (0.60 petition ratio, 0.25 quorum, 7.5% contingency, 60-point eligibility, 7-day study gap, 30/365-day embargoes, 3.0/2.0 effectiveness targets) + Decimal-exact `contingency_cents`/`allocated_cents_for`
- `test_users.py` — `TEST_USERS` + per-instance builders; `Resident` is entity-backed so all ownership-gated calls thread real resident ids
- `fixtures.py` — 5-tier composite pipeline (`setup_petition_open` → `setup_petition_met` → `setup_study_collecting`/`setup_ranking_eligible` → `setup_funded` → `setup_ballot_ready`/`setup_ballot_open`/`setup_consent_granted` → `setup_installation_planned`/`setup_installed`/`setup_effectiveness_certified`), plus `build_certified_request` and `drive_funded_request_to_ballot_open` for multi-request waterfall/crew scenarios

**`test_suite/`**: `conftest.py` + 9 test files clustered by concern (`test_01` registration/filing, `test_02` petitions, `test_03` studies/scoring, `test_04` funding waterfall, `test_05` treatment plans, `test_06` ballots, `test_07` work orders, `test_08` effectiveness/removal, `test_09` security/envelope/lookup).

## Counts
- **87 tests total: 36 queue A (all 18 difficulty instances × exactly 2 tests) + 51 queue B (all 51 non-stub corner instances × 1 test)**
- **Instances skipped: none.** Every non-stub instance passed the PRD-first two-condition filter. The 8 `excluded_because:` stubs were not translated; all 8 stub cross-references resolve to real difficulty instances.
- Two derivability judgments worth noting: (1) the two `priority_pair_validation_conflict` instances were kept because PRD §2.10 explicitly states the nine-tier strict ordering ("the earliest failing tier produces the rejection"); (2) the pagination instance's `status=SUBMITTED` filter param was dropped (PRD's endpoint table doesn't name request filters) while the fully-derivable limit/offset/total_count/has_more assertions were kept; version==1-at-creation assertions were omitted everywhere (PRD never pins the initial version).

## Stage 2 self-check (tag audit)
- Every one of the 87 tests ends its docstring with exactly one `Design:` line; all tags resolve to real instances; no tag points at a stub; no untagged or dual-tagged tests.
- Every difficulty instance has ≥2 tests; every non-stub corner instance has ≥1 test.
- Citation audit: every quoted docstring sentence greps verbatim (whitespace-normalized) in `PRD.md` — PASS.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere — PASS.
- `pytest --collect-only` collects 87 tests cleanly; pyflakes clean; no "scaffold" references in generated code outside the mandated verbatim instance tag.

## Step 7: Run Tests and Iterate — 2026-08-13T18:06:00.000Z

All 8 rounds pass: 87/87 in every round, 0 failures, 0 errors. The benchmark exit criteria are met.

## Summary

**Iterations run:** 2 (sweep 1 surfaced failures; sweep 2 after the fix is fully green — 87/87 × 8 rounds).

**Tests deleted:** None. Every failing test traced verbatim to PRD §3.4 and expressed it faithfully — no PRD-silence or unique-derivability deletions were warranted.

**Fixes applied to `test_helpers/`:** None. Fixtures, factories, and role-header builders were all consistent with the PRD; the three failures were pure implementation bugs.

**Fixes applied to `implementation/`:** One fix, one file:
- `workspace/implementation/routes/cycles.py`, function `publish_ranking`: added the missing `cycle["status"] = "RANKING_PUBLISHED"` transition on successful publication. PRD §3.4 states "Closing a cycle is permitted only from `RANKING_PUBLISHED`" and "on a re-publication the pool is every `RANKING_ELIGIBLE` request citywide plus this cycle's own `WAITLISTED` requests returning for another chance" — both presuppose that publishing moves the cycle from `OPEN` to `RANKING_PUBLISHED`. Without the transition, (a) `close_cycle` always rejected with `ERR_CYCLE_INVALID_STATE` (broke `test_waitlisted_request_cycles_back_on_close` and `test_publish_closed_cycle_rejected_terminal_lockdown` at setup), and (b) re-publication never folded the cycle's own `WAITLISTED` requests back into the pool, yielding a spurious `ERR_NO_ELIGIBLE_REQUESTS` (broke `test_stale_cycle_version_rejected_on_republish`). The three deterministic failures shared this single root cause; the one-line fix resolved all three.

## Step 8: Finalize PRD — 2026-08-13T18:10:00.000Z

Done. `workspace/PRD_FINALIZED.md` written with a single, minimal revision.

## Summary

**Line counts / delta:** PRD.md = 327 lines; PRD_FINALIZED.md = 327 lines; 0% line-count delta (one sentence revised in place, no lines added or removed).

**Changes (one total):**
- §3.4 — revise — the per-publication effects sentence now reads "Each publication stamps `published_at` from the logical clock, moves the cycle's status from `OPEN` to `RANKING_PUBLISHED` — a re-publication leaves the cycle in `RANKING_PUBLISHED` — and increments the cycle's `version` by one." This pins the transition Step 7 added to the implementation (`cycle["status"] = "RANKING_PUBLISHED"` on successful publication) — `workspace/implementation/routes/cycles.py:124`.

**Why this was the only edit:** The `<step_7_diff>` lists exactly one fix (one file, one line): the missing `OPEN → RANKING_PUBLISHED` transition in `publish_ranking`. PRD §3.4 previously said a cycle is born `OPEN` (line 171), that publishing is permitted from `OPEN` or `RANKING_PUBLISHED` (line 173), and that closing requires `RANKING_PUBLISHED` (line 177) — but never stated that publication itself produces the `RANKING_PUBLISHED` state. That was a genuine PRD silence, not a prose/impl mismatch elsewhere, so one scoped sentence fixes it. No other PRD text required changes.

**Per-edit pre-edit search log (edit 1, the only edit):**
- (a) Subject: funding-cycle `status` lifecycle, specifically the publication-time transition into `RANKING_PUBLISHED`.
- (b) Implementation paths enumerated and read/grepped: `cycles.py:30-44` (cycle born `OPEN`); `cycles.py:79-81` (publish state gate accepts `OPEN`/`RANKING_PUBLISHED`); `cycles.py:87-93` (re-publication pool branch fires only when status is already `RANKING_PUBLISHED`); `cycles.py:121-127` (success effects: `published_at`, the status assignment at :124, single version increment); `cycles.py:130-146` (close gate requires `RANKING_PUBLISHED`, transitions to `CLOSED`, cycles back `WAITLISTED` requests); `plans.py:59-77` (plan-approval re-baseline reads/writes only cycle budget fields, never status); `helpers.py:92-115` (`tally_ballot` CONSENT_DENIED compensating release touches only budget fields, never status). A repo-wide grep for `RANKING_PUBLISHED` and `cycle["status"]` confirmed no other readers or writers exist.
- (c) Wording adjustment: placed the clause inside the existing per-publication effects sentence (rather than the close paragraph) and added the explicit "a re-publication leaves the cycle in `RANKING_PUBLISHED`" parenthetical, because `cycles.py:124` assigns the status unconditionally on every successful publication — covering both the first-publication (`OPEN → RANKING_PUBLISHED`) and re-publication (idempotent) paths. No claim was made about cycle status in plan approval or ballot fund-release paths, which the implementation performs irrespective of cycle status; the wording makes no universal claims beyond the publication operation itself.

## Step 9: Complete PRD — 2026-08-13T18:30:00.000Z

Done. `workspace/PRD_COMPLETED.md` written (copied from PRD_FINALIZED.md, then edited in place).

**Stats**
- Source: `PRD_FINALIZED.md` (327 lines / 54,726 chars) → `PRD_COMPLETED.md` (329 lines / 57,007 chars); char-delta **+2,281**, line-delta **+2** (the two §5 catalogue rows).
- Counts: **19 ambiguity-pins, 0 mismatch-revisions** — every gap found was PRD silence; no PRD prose contradicted the implementation (PRD_FINALIZED's earlier fix of the `OPEN → RANKING_PUBLISHED` transition already matched `cycles.py:124`).

**Changes** (all inserts unless noted):
- §2.1 — insert — ambiguity — resident-identity resolution heads the existence tier, before any path/body identifier — `implementation/auth.py:34-40`
- §2.2 — insert — ambiguity — `api_request_timestamp` is taken from the logical clock, not wall-clock — `implementation/envelope.py:17-21`
- §2.3 — insert — ambiguity — out-of-range/unparseable `limit`/`offset` are clamped/floored to defaults, not rejected — `implementation/validate.py:135-147`
- §2.3 — insert — ambiguity — identical-`created_at` ties break by creation sequence, earliest first — `implementation/envelope.py:73-76`
- §2.3 — insert — ambiguity — `total_count` counts the full filtered set; `has_more` = `offset + page size < total_count`; meta echoes post-clamping values — `implementation/envelope.py:52-61`
- §2.4 — insert — ambiguity — clock adopts `to_iso8601` verbatim; no monotonicity check — `implementation/routes/clock_routes.py:15-22`
- §2.5 — insert — ambiguity — `version` starts at one on creation — `implementation/routes/segments.py:39` (and all other creations)
- §2.9 + §5 — insert — ambiguity — unmatched paths fail `ERR_NOT_FOUND` (404), unsupported methods `ERR_METHOD_NOT_ALLOWED` (405), both in the standard envelope; two catalogue rows added — `implementation/app.py:25-32`
- §2.10 tier 8 — insert — ambiguity — undeclared body fields are ignored, not rejected — `implementation/validate.py:43-57`
- §3.2 — insert — ambiguity — request birth shape: `allocated_cents` zero; `petition_opened_at`, `petition_deadline_at`, `required_signatures`, `signature_count`, `certified_score`, `funding_cycle_id`, `citywide_rank`, `installed_at` null until assigned — `implementation/routes/requests.py:61-82`
- §3.2 — insert — ambiguity — a resident retracting another's signature is rejected `ERR_FORBIDDEN` — `implementation/routes/signatures.py:16-19`
- §3.3 — insert — ambiguity — study born with `observation_count`/`valid_observation_count` at zero — `implementation/routes/requests.py:214-215`
- §3.3 — insert — ambiguity — observations stored verbatim; §2.6 rounding applies at aggregate computation, never at intake — `implementation/routes/studies.py:63-73`, `calc.py:54-61`
- §3.3 — insert — ambiguity — return-for-recollection leaves provisional aggregates in place until the next analysis — `implementation/routes/studies.py:112-121`
- §3.5 — insert — ambiguity — plan born with `submitted_at`/`approved_at`/`approved_by_user_id` null — `implementation/routes/requests.py:275-289`
- §3.6 — insert — ambiguity — ballot born with the three vote counters at zero — `implementation/routes/requests.py:314-330`
- §3.7 — insert — ambiguity — work order born with `scheduled_date`/`duration_days`/`reviewed_by_user_id`/`installed_at` null — `implementation/routes/requests.py:353-367`
- §3.8 — insert — ambiguity — removal request born with `decided_by_user_id` null — `implementation/routes/requests.py:390-401`
- §4 table — revise — ambiguity — `GET /api/requests` filter set pinned to `street_segment_id`, `created_by_resident_id`, `status`, `funding_cycle_id` (was the vague "with filters") — `implementation/routes/requests.py:93-101`

**Verified already-pinned (no change):** all endpoint/role mappings, the nine-tier validation order and per-endpoint check ordering, both OCC guards (missing version field → 400 via tier 8), petition/ballot sweep semantics (strictly-past, inclusive threshold boundaries), the 7-day inclusive study-window buffer, half-open crew-overlap with adjacency allowed, the ranking tie-break chain, strict-stop waterfall with inclusive exact-fit, the three-link approval cascade including negative-delta re-baseline, consent-denial compensating release, plan supersession set, request-revision landing in `DRAFT`, ballot integer cross-multiplication, effectiveness verdicts computed on the rounded reductions, 201/200/204 status assignments, and event-record immutability (`id`+`created_at` only).

## PIPELINE COMPLETE — all 9 steps done; workspace/PRD_COMPLETED.md exists.
