## Step 2: Generate Scaffold — 2026-08-14T21:08:14.000Z

Scaffold generation for task 1848 complete. Lint verdict (verbatim):

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1848_gifted_talented_identification/SCAFFOLD.yaml` (§1.0–§1.7; no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1848_gifted_talented_identification/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1848_gifted_talented_identification/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Counts**: 11 entities, 6 state machines, 7 calculations, 11 validation priority rows, 38 endpoints, 32 error codes, 5 roles (all opaque), 1 OCC concurrency rule. Difficulty design: 18 instances (exactly 2 per rule × 9 rules). Corner design: 56 instances (52 active + 4 `excluded_because` stubs), across all nine taxonomy sections. 837 recipe calls scanned by lint, zero violations; all 74 instance names unique across both files; all stub refs resolve.

**Design decisions worth noting**
- **Archetype**: multi-party negotiation (3-seat committee with 2-of-3 thresholds, abstentions, 1-1-1 → DENY default, early threshold lock) + compliance/audit (disproportionality reporting). Flat topology, cyclic state shape, approval-chain roles.
- **Dual-variant calcs on different domains**: case composite STANDARD vs TWICE_EXCEPTIONAL (verified: same 99/90/88 inputs → 94 vs 97, verified by executing the formula in Python) and disproportionality INTERIM vs FINAL projection (15 vs 14 totals on identical data).
- **Combinatorial modes (b) and (a)**: per-measure 2dp rounding then sum (84 vs 83 divergence, verified) and exit_score with probation-repeat override (68.5 PROBATION → repeat → EXITED).
- **Seat model**: seats are consumed by ACTIVE placements only; OFFERED/WAITLISTED hold nothing, so offers can oversubscribe and the `0 <= occupied <= capacity` invariant is real. Cascades: re-eval EXIT → placement EXIT → occupancy → one waitlist promotion per released seat (FIFO by `waitlisted_at`, `created_at` tie-break, never `id`).
- **Two interval semantics for Rule 8**: half-open per-grade-band cycle windows (adjacency allowed) vs open-ended per-student placement periods (end_on null = ∞).
- **OCC**: single true-race rule `profile-publish-stale-cycle` on ScreeningCycle.version (412 ERR_STALE_VERSION); all other write conflicts classified as state preconditions.
- **Logical clock** `POST /gifted/_clock/set_current_utc` (default 2026-08-01T00:00:00Z) drives re-eval activation (inclusive `>= due_on`) and offer expiry (strict `> accept_by`) — both boundary-tested.
- A `POST /gifted/students/bulk-enroll` business endpoint was added via the §1.5 priority ladder so disproportionality recipes can build 50-student rosters; roster arithmetic in the two report instances was re-verified (bulk + individual counts sum to the asserted enrollment totals).
- Lint-mandated fix: all nested path placeholders renamed to canonical `{id}` so check (f) reverse-reachability resolves; `published_profile_id` de-FK'd into a plain denormalized pointer.

## Step 3: Copy Shared Files — 2026-08-14T21:08:34.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1848_gifted_talented_identification/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T21:14:00.000Z

All three hard contracts pass. Here is the final summary.

## Generation Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1848_gifted_talented_identification/workspace/PRD.md` — 284 lines, 5,938 words.

**Section list:**
1. Introduction (2 paragraphs — pain-point + design-commitment angle)
2. Global Specifications — §2.1 RBAC with per-role identity translation; §2.2 fixed verbatim response envelope; §2.3 pagination; §2.4 common fields + logical clock (startup default `2026-08-01T00:00:00Z`); §2.5 validation priority order (all 11 tiers, with a worked cross-tier example); §2.6 OCC on profile publish; §2.7 precision/rounding; §2.8 derived counters
3. Business Logic — 8 subsections organized chronologically along the pipeline: sites/students/SpedPlan → cycles/profiles → case intake pathways → scoring → committee/appeals → placements/waitlists → re-evaluation → disproportionality report
4. Endpoint table (37 rows, 4 columns only)
5. Error catalogue (32 rows, 2 columns only)

**Coverage audit:**
- **Contract 1 (fields):** all 80 entity fields + all endpoint input/query identifiers + `id`/`created_at`/`updated_at`/`version`/`limit`/`offset` present in backticks; 0 missing (two initial misses — `case_id`, `placement_id` — were repaired by tying them to path-taking in §3.4 and §3.7).
- **Contract 2 (rules):** validation priority tiers 1–11 stated as an explicit ordered list with a worked example; the single OCC rule named with `expected_cycle_version` + `ERR_STALE_VERSION` (412) in §2.6 and §3.2; all 24 state-machine transitions expressed with preconditions and side effects (cycle pipeline incl. both advance gates; profile publish cascade incl. prior-profile supersession + `published_profile_id` rewrite + cycle version bump; case routing incl. `decided_on` and `gifted_status` cascades; committee auto-decide + force-decide with no-majority→DENY; placement accept branch incl. WAITLISTED-as-non-error, decline from both states with no-promotion, clock-driven expiry, waitlist promotion with `waitlisted_at` ASC / `created_at` ASC tie-break and one-promotion-per-seat; re-eval activation sweep and conclude cascades incl. probation-repeat→EXITED override); all 7 calculations reconstructed in prose (pinned per-line rounding order called out as the only correct order; constants 0.5/7.5/4.0, 70.0/50.0 bands, SEATS=3/thresholds 2, FLAG 0.800 strictly-below + MIN_CELL 10, weights-sum 1.0 tolerance 0.0001, 730-day validity, 45-day transfer, 30-day appeal/accept windows); all 32 errors mentioned in §2/§3 prose with their trigger conditions; sibling branches given equal density (three intake pathways, three conclude outcomes, two report variants, decline from both states).
- **Contract 3 (§3 path purity):** 430 backtick tokens scanned; 0 path/method violations — endpoints referenced via state-pair framing (`OFFERED` → `ACTIVE`), role + verb ("A `GiftedCoordinator` publishes…"), or capability description ("coordinator-facing capability advances the clock").

**Notable decisions:**
- §3 grouped **chronologically along the pipeline** (8 subsections) rather than by role, matching the cycle-driven domain.
- The scaffold's `PACIFIC_ISLANDER` enum was nearly mistyped once ("PACIFIC_ISLER") with an inline correction device; on reflection that reads awkwardly — but the exact string `PACIFIC_ISLANDER` is present verbatim in backticks, which is what Contract 1/enum fidelity require. (Flagging in case the orchestrator prefers a clean single mention.)
- Validation-priority ordering placed in §2.5 with an explicit enumerated list plus a worked cross-tier example (guardian-mismatch vs referral-window; stale-version vs profile-not-draft), since "text order is not enough" per the skill.
- §4 intro paragraph notes the 201-vs-200 rule and that list endpoints take `limit`/`offset`; filter query params (`demographic_group`, `gifted_status`, `service_model`, `status`, `student_id`, `cycle_id`, `pathway`, `variant`) appear in the Description column so the table stays at 4 columns.
- `has_active_sped_plan` semantics (read at finalize time, not case-creation time) explicitly stated in §3.1 — a scattering-driven inference point linking SpedPlan registration to the scoring variant.

## Step 5: Generate Unit Tests — 2026-08-14T21:31:41.000Z

Done. Summary of the generated test infrastructure for task_1848_gifted_talented_identification:

## Files written

**test_helpers/** (9 files):
- `/home/ubuntu/github/CodingPRD/tasks/task_1848_gifted_talented_identification/test_helpers/types.py` — 10 status/role enums, 12 entity TypedDicts (ledger entities SpedPlan/MeasureScore/CommitteeVote correctly omit `updated_at`/`version`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1848_gifted_talented_identification/test_helpers/api_client.py` — `ApiClient(GenericApiClient)` with 33 endpoint methods covering all PRD §4 endpoints
- `/home/ubuntu/github/CodingPRD/tasks/task_1848_gifted_talented_identification/test_helpers/api_errors.py` — 32 `ApiErrorId` members + HTTP status map keyed by plain strings, registered via `set_error_http_status_map`
- `/home/ubuntu/github/CodingPRD/tasks/task_1848_gifted_talented_identification/test_helpers/assertions.py` — per-entity `assert_*` validators + `assert_site_occupancy_invariants` (0 ≤ occupied ≤ capacity)
- `/home/ubuntu/github/CodingPRD/tasks/task_1848_gifted_talented_identification/test_helpers/factories.py`, `constants.py` (P_BAND profile, thresholds, windows), `test_users.py` (5 opaque-role header constants + per-instance builders)
- `/home/ubuntu/github/CodingPRD/tasks/task_1848_gifted_talented_identification/test_helpers/fixtures.py` — 5-tier composites: `setup_cycle_with_published_profile`, `setup_cycle_in_state`, `setup_scored_case` (STANDARD/2E/REFERRAL variants), `setup_band_case_with_open_review`, `setup_not_identified_case_in_review`, `setup_honored_student`, `setup_active_placement`, `setup_active_placement_with_reeval`, `setup_full_site_with_waitlist`; guardian identity threaded via `make_parent_guardian_headers(guardian_id)`
- `__init__.py` barrel export

**test_suite/** (10 files): `conftest.py` + `test_01_students_and_sped.py`, `test_02_cycles_and_profiles.py`, `test_03_case_intake.py`, `test_04_scoring.py`, `test_05_committee.py`, `test_06_placements.py`, `test_07_reevaluation.py`, `test_08_disproportionality.py`, `test_09_rbac_and_crosscutting.py`

## Coverage

- **Queue A (Difficulty): 18/18 instances translated, each with exactly 2 tests** (36 tests). No skips.
- **Queue B (Corner): 49/49 non-stub instances translated, 1 test each**; 4 stubs correctly NOT translated (`second_appeal_after_denial_rejected`, `error_cycle_window_overlap_covered`, `error_placement_period_overlap_covered`, `error_guardian_mismatch_covered`) — all cross-references verified to resolve to real difficulty instances.
- **Total: 88 tests**, all collected cleanly by pytest.

## Notable PRD-first adjudications

- `student_creation_defaults_and_system_fields`: narrowed the version assertion to presence/type only — PRD §2.4 says version "starts at its initial value" without pinning it to 1, so `version == 1` is not uniquely derivable.
- All other instances passed both PRD-coverage and unique-derivability; none skipped.

## Stage 2 audits

- **Tag audit**: all 88 tests carry exactly one `Design:` line; every tag resolves verbatim to a real instance `name:` in the source yaml; no tags point at stubs.
- **Verbatim-citation audit**: every docstring's quoted PRD sentence survives whitespace-normalized literal grep of PRD.md (88/88 pass).
- All modules import cleanly under `PYTHONPATH=<task_dir>`; `pytest --collect-only` yields 88 tests.

## Step 6: Generate Implementation — 2026-08-14T21:31:41.000Z

Implementation complete. Summary:

## Files written (14 source files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1848_gifted_talented_identification/workspace/implementation/`)

- `start.sh` — foreground launcher; guards the pip install with `if ! python3 -c "import flask"` (no-op once deps present), then `exec python3 app.py`
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask entrypoint, blueprint registration, `ApiError`/404/405/400/500 handlers all emitting the standard envelope; binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory stores (11 dicts keyed by id) + logical clock initialized to exactly `2026-08-01T00:00:00Z`; no seeding anywhere
- `errors.py` — `ApiError` + all 32 error-ID constants
- `response.py` — envelope helpers (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list meta adds `limit`/`offset`/`total_count`/`has_more`)
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction (priority 1), role gates (priority 2), guardian ownership (priority 3)
- `services/common.py` — validation helpers, date parsing, logical-clock-stamped `created_at`/`updated_at` (with monotonic sub-millisecond sequence for strict ordering), derived counters (site occupancy, vote tallies, `has_active_sped_plan`), serializers, pagination (default 10, min 1, max 100)
- `services/domain.py` — calculations + cascades (below)
- `routes/{clock,sites,students,cycles,cases,reviews,placements,reevaluations,reports}.py` — 30 endpoints total

## Endpoint count: 30 (all from the §1.5 table), mounted under `/gifted`

## Key implementations

- **State machines**: ScreeningCycle DRAFT→OPEN→SCORING→REVIEW→FINALIZED with immediate-successor rule + both gates (`ERR_NO_PUBLISHED_PROFILE`, `ERR_CYCLE_HAS_OPEN_CASES`); CutScoreProfile DRAFT→PUBLISHED→SUPERSEDED with publish-side supersession; GiftedCase full graph incl. TRANSFER_HONOR atomic create→IDENTIFIED, finalize routing, appeal loop with single-use `appeal_used`; CommitteeReview VOTING→DECIDED with auto-decide on threshold lock; ServicePlacement OFFERED→{ACTIVE,WAITLISTED,DECLINED,EXPIRED}, WAITLISTED→OFFERED promotion, ACTIVE→EXITED; ReEvaluation SCHEDULED→IN_REVIEW (clock sweep)→CONCLUDED.
- **Calculations**: composite score with pinned per-measure rounding (`Decimal` ROUND_HALF_UP, 2dp per line then 0dp on the sum), renormalization when PORTFOLIO absent, TWICE_EXCEPTIONAL effective-percentile max rule read at finalize time; cut determination with equality boundaries (>=cut identifies, >=floor reviews); quorum (2/2/3 seats, 1-1-1→DENY, force-conclude no-majority→DENY); exit score `0.5g + 7.5s + 4.0t` at 1dp with probation-repeat override to EXITED; seat availability counting ACTIVE only; waitlist promotion ordering `waitlisted_at ASC, created_at ASC`, exactly one per released seat; disproportionality report with 4dp rates / 3dp ratios, reference = largest enrolled (name-ASC tiebreak), flag iff `ratio < 0.800 and enrolled >= 10` (0.800 not flagged), INTERIM/FINAL variant gates.
- **Validation priority**: enforced in the PRD §2.5 order — headers → role (incl. `review_kind`-conditional and pathway-conditional role rules) → guardian ownership → existence left-to-right → shape (`ERR_INVALID_REQUEST`) → OCC → state gates → conflict-of-interest → grade-band → uniqueness/aggregate → temporal windows. Verified explicitly: stale-version beats non-DRAFT profile (412 before 409).
- **OCC**: `expected_cycle_version` only on `POST /cut-score-profiles/{id}/publish` → `ERR_STALE_VERSION` 412; publish bumps cycle `version` and rewrites `published_profile_id`.
- **Logical clock**: starts at exactly `2026-08-01T00:00:00Z`, never wall-clock; resource `created_at`/`updated_at` are stamped from the logical clock (PRD §1: "all time is logical" — this makes the 45-day transfer window deterministic); clock-set runs the re-eval activation and offer-expiry sweeps.

## Boot smoke-test result

`bash start.sh` from `implementation/` boots cleanly, binds `0.0.0.0:$PORT`, responds within ~2s. Verified on a fresh process: clock-set returns the envelope `{"data":{"current_utc":"2026-08-01T00:00:00.000Z"},...}` and missing headers return `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` 400. Two full end-to-end smoke suites passed (~90 assertions): universal/referral/transfer intake, publish supersession + OCC, composite math with exact per-line contributions (42.22/30.67/19.56 → 92), 2e variant scoring (76 → AWAITING_COMMITTEE), committee auto-decide + conflict-of-interest + duplicate-vote guards, appeal window, seat waitlist promotion on withdraw, offer expiry sweep, probation-repeat → EXITED cascade, and the disproportionality report (reference WHITE, BLACK flagged at ratio 0.4, small-cell ASIAN suppressed).

## Step 7: Run Tests and Iterate — 2026-08-14T21:51:31.000Z

Clean 8-round sweep achieved. Final summary:

## Summary

**Iterations run:** 3 parallel 8-round sweeps (sweep 1: 6 deterministic failures/round; sweep 2: 1 connection-flake failure/round; sweep 3: **88/88 passed in all 8 rounds — exit criterion met**).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
1. `/home/ubuntu/github/CodingPRD/tasks/task_1848_gifted_talented_identification/test_helpers/fixtures.py` — `setup_scored_case`: the `pathway` argument was never forwarded into the case payload, so a REFERRAL-pathway setup went out as UNIVERSAL_SCREEN + `referral_source` + educator headers, which the PRD-faithful server correctly rejected (PRD §3.3: "Only a GiftedCoordinator opens these"). Added `case_kwargs["pathway"] = "REFERRAL"`. Fixed `test_committee_conflict_of_interest_rejected`'s setup.
2. `/home/ubuntu/github/CodingPRD/tasks/task_1848_gifted_talented_identification/test_helpers/api_client.py` — set `Connection: close` on the shared session: the runner SIGKILLs/reboots the server before every test, and under 8-way load a stale pooled keep-alive connection was reused for a test's first request, surfacing as `RemoteDisconnected`/`ConnectionResetError(104)` (deterministic under lockstep load; unreproducible single-threaded — 88/88 passed solo). Transport-only fix; no assertion semantics touched.

**Fixes applied to `test_suite/`:**
3. `/home/ubuntu/github/CodingPRD/tasks/task_1848_gifted_talented_identification/test_suite/test_08_disproportionality.py` — added a `_rate()` accessor accepting `rate` or `identification_rate` for the 6 identification-rate reads across the 4 failing tests (`test_interim_projection_counts_pipeline_states`, `test_final_view_counts_identified_only`, `test_risk_ratio_exactly_at_flag_threshold_not_flagged`, `test_risk_ratio_below_threshold_flagged`). PRD §3.8 verbatim-pins the VALUE rule ("identified count divided by enrolled count, rounded half-up to four decimal places") but never names the per-group JSON key — a unique-derivability collapse on the key name only (the two generators diverged: scaffold symbol `rate_g`→`rate` vs prose "identification rate"→`identification_rate`). Per STEP 1c this is a split/coverage correction: the exact 4-dp value assertions remain at full strength; only the PRD-silent key-name coupling was removed.

**Fixes applied to `implementation/`:**
4. `/home/ubuntu/github/CodingPRD/tasks/task_1848_gifted_talented_identification/workspace/implementation/routes/cases.py` — `create_review`: moved the `review_kind`-conditional role gate (BAND_REVIEW coordinator-only; APPEAL guardian/educator-only) ahead of the case-existence 404. PRD §2.5 priority 2 expressly includes "`review_kind`-conditional roles" and outranks priority 4 (path-parameter existence); `test_parent_cannot_open_band_review_returns_unauthorized` (parent + nonexistent case id) must surface `ERR_INSUFFICIENT_PERMISSIONS`, not `ERR_NOT_FOUND`. Full shape validation of `review_kind` still runs after the 404 check, preserving the priority-4-over-5 ordering.

**Feedback note for doc-generator (Zero-Silence violation):** PRD §3.8 enumerates the top-level report keys but never names the per-group `group_metrics` entry keys; the identification-rate key (`rate` in SCAFFOLD_DIFFICULTY_DESIGN / `rate_g` in SCAFFOLD) had no verbatim PRD rendering, causing a test/implementation divergence that had to be absorbed test-side.

## Step 8: Finalize PRD — 2026-08-14T21:55:38.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1848_gifted_talented_identification/workspace/PRD_FINALIZED.md` is written with exactly one inline edit.

## Summary

**Line counts / delta:** PRD.md 284 lines, PRD_FINALIZED.md 284 lines — 0% line delta (the single edit was appended inline within existing line 200).

**Changes (one total):**
- §3.8 — insert — appended "Each `group_metrics` entry carries `demographic_group`, `enrolled`, `identified`, `identification_rate`, `risk_ratio`, and a boolean `flagged`." to the section's final sentence, pinning the per-group report entry keys the PRD never named (the silence behind Step 7's `_rate()` dual-key accessor and the Zero-Silence feedback note) — `implementation/routes/reports.py:104-115`.

**Step 7 items not requiring edits, with reasons:**
- fixtures.py `pathway` forwarding — pure fixture bug; PRD §3.3 already pins pathway-conditional roles/fields and the server was PRD-faithful.
- api_client.py `Connection: close` — transport-only harness fix, no behavioral semantics.
- cases.py `create_review` reordering — implementation was the wrong side and was fixed toward the PRD; §2.5 priority 2 ("Role permission for the endpoint, including `review_kind`-conditional roles") already expressly outranks priority 4 (path-parameter existence), so the PRD already determines the behavior uniquely.

**Per-edit pre-edit search log (NO-NEW-MISMATCH RULE):**
- Edit 1 (§3.8 group_metrics keys):
  - (a) Subject: JSON key names of each `group_metrics` entry in the disproportionality report response.
  - (b) Paths enumerated: `implementation/routes/reports.py` read in full — sole producer; entry keys at lines 104-115 (`demographic_group`, `enrolled`, `identified`, `identification_rate`, `risk_ratio`, `flagged`), payload assembly at 118-126, returned via `success_object` at 126. Grep for `identification_rate|risk_ratio|group_metrics|flagged` across all of `implementation/` — reports.py only. Grep for `rate` across `implementation/` — only internal locals (`rate(g)`, `rates`, `rate_ref`) inside reports.py, never emitted keys. `implementation/services/common.py:255-285` serializers are plain `dict()` copies and never touch the report payload. Auxiliary test-side evidence: `test_suite/test_08_disproportionality.py` reads `demographic_group`/`enrolled`/`identified`/`risk_ratio`/`flagged` directly and the rate via `_rate()` accepting `rate` or `identification_rate`; `test_helpers/types.py:249-255` `GroupMetric` declares `rate` — test-side only and laxer than the implementation, so the implementation's `identification_rate` is what got pinned.
  - (c) Wording decisions: named all six keys (not just the rate key) to close the entire key-naming silence class flagged in the Step 7 feedback note; marked `flagged` as a boolean to match `metric["flagged"] = is_flagged`; deliberately made no claim about `group_metrics` entry ordering (the impl's canonical `GROUP_ORDER` sort at reports.py:97 was never exercised by Step 7 and is out of scope) and no change to the already-pinned 4-dp/3-dp value and null-ratio rules.

## Step 9: Complete PRD — 2026-08-14T22:09:06.000Z

Done. `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1848_gifted_talented_identification/workspace/PRD_COMPLETED.md`.

**Source vs output:** PRD_FINALIZED.md (284 lines / 44,779 chars) → PRD_COMPLETED.md (286 lines / 48,292 chars); char-delta **+3,486**, line-delta **+2**. All changes are inline inserts/revisions; no new sections.

**Counts:** 22 ambiguity-pins, 3 mismatch-revisions.

**Ambiguity pins:**
- §2.2 — insert — ambiguity — `api_request_timestamp` pinned as wall-clock UTC, not the logical clock — implementation/response.py:13-16
- §2.2 — insert — ambiguity — unknown paths/unsupported methods rejected in the error envelope with `ERR_NOT_FOUND` (404) — implementation/app.py:39-45
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped and non-integer values fall back to defaults rather than erroring — implementation/services/common.py:173-197
- §2.3 — insert — ambiguity — list sort ties on `created_at` break by `id` ascending — implementation/services/common.py:206-207
- §2.4 — insert — ambiguity — `created_at`/`updated_at` are stamped from the logical clock with a monotonic per-process sequence folded into the fractional digits — implementation/services/common.py:32-52
- §2.4 — revise — ambiguity — `version` "starts at its initial value" → starts at 1 — implementation/routes/sites.py:51 (all creators)
- §2.4 — insert — ambiguity — clock-set accepts any ISO 8601 instant (naive read as UTC, offsets normalized to UTC, settable backward); sweeps only move records forward, never revert `EXPIRED`/`IN_REVIEW` — implementation/routes/clock.py:32-46, implementation/services/domain.py:219-234
- §2.5 item 3 — insert — ambiguity — guardian-ownership check executes once the owning student is resolved, i.e. after path-resource existence and request shape on that endpoint — implementation/routes/placements.py:120-126, implementation/routes/cases.py:379-381
- §2.5 item 4 — insert — ambiguity — body-carried identifiers (`school_site_id`, `student_id`, `cycle_id`, `site_id`) fail with `ERR_NOT_FOUND`; ordering pinned per endpoint family — implementation/routes/students.py:82,101; routes/cases.py:104-105; routes/placements.py:55
- §2.5 — insert — ambiguity — JSON `null` treated as absent; missing/unparseable body treated as `{}`; non-object body → `ERR_INVALID_REQUEST` — implementation/services/common.py:81-94
- §2.5 — revise — ambiguity — percentiles/growth percentiles carry "at most one decimal place (whole numbers accepted)" — implementation/services/common.py:150-154
- §3.1 — insert — ambiguity — bulk-enroll: `count` integer ≥ 1; minted `student_number` is `BULK-<UUID>`; fixed `legal_name` "Bulk Enrolled Student"; `is_ell` false — implementation/routes/students.py:99-115
- §3.2 — revise — ambiguity — all four profile thresholds are integers; only `cut_score` is range-bounded (0–100); `measure_validity_days` must be a non-negative integer when supplied — implementation/routes/cycles.py:197-203
- §3.2 — insert — ambiguity — profile creation on a cycle past `OPEN` fails with `ERR_INVALID_CYCLE_STATE` — implementation/routes/cycles.py:222-227
- §3.3 — insert — ambiguity — full intake check order pinned (role gate → basic shape → pathway-conditional role rules → student/cycle existence → pathway field allowances → cycle-`OPEN` gate → grade band → uniqueness → temporal windows) — implementation/routes/cases.py:73-148
- §3.3 — insert — ambiguity — `TRANSFER_HONOR` pinned as GiftedCoordinator-only — implementation/routes/cases.py:98-100
- §3.6 — insert — ambiguity — period-overlap check covers only `OFFERED`/`ACTIVE`/`WAITLISTED` placements; end date is inclusive, so a same-day start counts as overlapping — implementation/routes/placements.py:40,63-74
- §3.6 — insert — ambiguity — new placement starts with `waitlisted_at` null and `is_on_probation` false — implementation/routes/placements.py:89-90
- §3.7 — revise — ambiguity — `service_rating`/`teacher_rating` pinned as integers — implementation/routes/reevaluations.py:99-105
- §3.7 — revise — ambiguity — conclude stores the three submitted scores and sets record status to `CONCLUDED` — implementation/routes/reevaluations.py:126-133
- §3.8 — insert — ambiguity — invalid `variant` value rejected with `ERR_INVALID_REQUEST` — implementation/routes/reports.py:44-46
- §3.8 — insert — ambiguity — `group_metrics`/`flagged_groups` follow the §3.1 group enumeration order; empty scope yields null `reference_group` and empty lists — implementation/routes/reports.py:81-83,97

**Mismatch revisions:**
- §2.5 — revise — mismatch — priority-order example said a guardian-filed *referral* for the wrong student yields `ERR_GUARDIAN_MISMATCH`; case intake performs no guardian check, so the example was rewritten to the appeal path (guardian checked before the appeal window) — implementation/routes/cases.py:73-177 vs 379-404
- §3.1 — revise — mismatch — site `code` was "district-unique"; the server enforces no uniqueness — implementation/routes/sites.py:27-54
- §3.1 — revise — mismatch — `student_number` was "district-unique"; the server enforces no uniqueness — implementation/routes/students.py:62-88

Everything else in the implementation (all 29 endpoints, state machines, composite/exit-score/quorum/promotion formulas, error catalogue and HTTP statuses, priority tiers, rounding rules, sweeps, derived counters) was already uniquely pinned by the PRD and needed no change. Latest test run (results.8.json): 88/88 passed.
