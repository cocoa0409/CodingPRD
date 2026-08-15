# Worklog — task_1957_touring_theatrical_company_management

## Step 1: Create Task Directory — 2026-08-15T03:00:00.000Z

Task directory `tasks/task_1957_touring_theatrical_company_management/` and `workspace/` pre-created by the pipeline launcher (Step 1 done externally per command args); orchestrator starts at Step 2. User directive: difficulty beyond Expert band.

## Step 2: Generate Scaffold — 2026-08-15T03:54:41.980Z

## Task 1957 — Touring Theatrical Company Management: scaffold generated

**Files written** (all three required, in the task directory):
- `/home/ubuntu/github/CodingPRD/tasks/task_1957_touring_theatrical_company_management/SCAFFOLD.yaml` (§1.0–§1.7; no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1957_touring_theatrical_company_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level `scaffold_difficulty_design:`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1957_touring_theatrical_company_management/SCAFFOLD_CORNER_DESIGN.yaml` (single top-level `scaffold_corner_design:`)

**Counts**: 12 entities, 42 endpoints, 33 error codes, 9 calculations, 11 state-machine entries (10 entities + Stop's two parallel dimensions), 2 OCC concurrency rules, 4 roles. Difficulty design: 24 instances (9 rules, ≥2 each, 3 rules carry a 3rd). Corner design: 53 active instances + 18 `excluded_because` stubs across all nine claim-taxonomy sections.

**Archetype / layers**: primary `pricing_engine` (guarantee-vs-split settlement waterfall + marginal tiered royalty), secondary `temporal_windowing` (routing windows with travel buffers, same-day curtain gaps). Layers: `dual_variant_calculation`, `cascading_side_effects`, `rate_threshold_triggers`, `optimistic_concurrency`. Flat topology (per diversity guidance), `segregation_of_duties` role model (settlement submit → approve → pay must be three distinct users), immediate consistency. Expert band targeted; difficulty pushed via density: the 12 entities are mutually gated (Stop×TechRiderCheck×Performance×Settlement is one tight knot; CastMember×CharacterTrack×CoverageAssignment×InjuryEvent another), not padded.

**Nine §0.5 rules satisfied**:
1. **dual_variant_calc** — settlement provisional (advance-sales estimate 4,550,000) vs final waterfall (4,000,000) on the fiscal domain; FULL_WEEK (140,000) vs ACTUAL_DAYS (80,000) per-diem on the cast-compensation domain; royalty marginal-vs-flat reading (105,000 vs rejected 135,000).
2. **combinatorial_formula** — mode (a) royalty with 3 inputs (share, threshold, recouped) and min/max+branch; mode (b) per-diem half-day rounding order pinned (120,691 vs 120,690); mode (c) wrap/recoup circular-look pinned by evaluation order (royalty 18,000 pre-flip → 24,000 post-flip on identical figures, recoup flips at exactly == capitalization).
3. **non_linear_state_machine** — Settlement SUBMITTED→DISPUTED→SUBMITTED cycle; Stop parallel booking×compliance dimensions; InjuryEvent branching fork with divergent side effects.
4. **transitive_cascade** — injury cascade depth 4 (injury→ON_LEAVE→coverage ACTIVATED + sibling-track SUSPEND→track exposure flips); tech-fail cascade depth 2 (check FAIL→NON_COMPLIANT→READY→ADVANCED revocation).
5. **priority_pair_validation_conflict** — auth-vs-state (SoD beats invalid-state on approve), state-vs-fiscal (amend on ADVANCED stop), shape-vs-state (negative gross on cancelled performance).
6. **boundary_precision_check** — 8th/9th weekly performance (count), royalty share == T vs T+10 (money: 60,000 vs 60,001), exactly-8.00h vs 8.25h overtime (time).
7. **cross_entity_state_dependency** — Performance→Stop, CoverageAssignment→CastMember, Stop→TechRiderCheck.
8. **resource_temporal_overlap** — route windows with mandatory travel buffer (rejected at equality, accepted at +1 day) vs same-day curtain min-gap with count cap (16:49 fails, 16:50 passes) — different resources and interval semantics.
9. **compensating_invariant** — budget identity (committed+spent+available == 50,000,000 across contract→cancel-at-61-days netting to zero) and royalty accrual (invariant over {APPROVED, PAID} across the dispute cycle: 0 → 105,000 → 105,000).

All formula-derived assertions were precomputed by executing the formulas in Python (settlement waterfall, royalty tiers, per-diem rounding, crew OT, penalties, wrap totals) and written as literals.

**Verification**: `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (42 endpoints, 24 §1.8 + 53 §1.9 active instances, 821 calls scanned, 0 violations). Additionally scripted and passed: instance-name uniqueness across both files, error-catalog bidirectional closure (referenced ↔ catalogued), grounds resolution into §1.1–§1.6, placeholder closure (zero unbound `${var}`), forbidden-vocabulary scan, enum-value closure, and per-entity/per-transition/per-calculation field completeness. A logical-clock endpoint with the mandated `2026-08-01T00:00:00Z` default supports all time-window rules.

One note: the lint's sub-resource FK check requires the literal path segment `{id}`, so sub-resource list paths use `{id}` (e.g., `GET /stops/{id}/performances`) while single-resource paths keep entity-named placeholders — call sites match either structurally.

## Step 3: Copy Shared Files — 2026-08-15T03:55:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1957_touring_theatrical_company_management/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-15T04:01:06.775Z

## PRD Generation Summary — Task 1957 (Touring Theatrical Company Management)

**Output written:** `/home/ubuntu/github/CodingPRD/tasks/task_1957_touring_theatrical_company_management/workspace/PRD.md` — confirmed on disk, **318 lines**.

**Constraint compliance:** Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced. No sibling task directory was read.

### Section structure
- **§1 Introduction** — 3 paragraphs (business context → lifecycle scope → the two pervasive themes: pinned-order money and derived/cascading state)
- **§2 Global Specifications** — 11 subsections: 2.1 RBAC, 2.2 Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md`, including `req_RANDOMALPHANUM123456` and `"data": { }`), 2.3 Pagination, 2.4 Identity/Timestamps/Versioning, 2.5 Monetary Precision, 2.6 OCC, 2.7 Nested Resolution, 2.8 Validation Pipeline Ordering, 2.9 Logical Clock, 2.10 Derived State, 2.11 Segregation of Duties
- **§3 Business Logic** — 10 subsections organized by business-process timeline: production setup → routing/budget/amendments → tech-rider certification → performances/box office → crew labor → per-diems → settlement waterfall/royalty → weekly wrap/recoupment → cast/tracks/coverage → injury protocol
- **§4 Endpoint Definitions** — 4-column table (Method, Path, Description, Authorized Role), all 41 endpoints
- **§5 Error Code Catalogue** — 2-column table, all 34 errors

### Scaffold section rendering
- **§1.1 Entities (12)** → scattered through §3 narratives by lifecycle; all 77 field names in backticks
- **§1.2 State machines (11, including the derived `compliance_status` dimension and the branching InjuryEvent fork)** → every transition rendered as state-pair prose with preconditions paired to error IDs and all cascade side effects stated
- **§1.3 Calculations (8)** → all rendered as precise natural-language formulas with pinned evaluation orders (waterfall taxes-then-levies; marginal royalty per-bracket rounding with explicit rejection of the flat reading; per-diem half-rate rounded first; crew pay per-line rounding, not sum-then-round; cancellation penalty 60/61-day boundary; wrap recoup-flip-after-posting; selector ranking kind → priority_rank → created_at with id never used)
- **§1.4 Validations (33)** → §2.8 renders the priority pipeline in explicit first-to-last order with per-tier error IDs; trigger conditions scattered into §3 workflows
- **§1.5 Endpoints (41)** → §4 locator table only; request payloads live solely in §3 prose
- **§1.6 Errors (34)** → §5 two-column catalogue; every ID also mentioned in §2/§3 prose near its trigger
- **§1.7 Roles (4)** → exact role spellings, per-endpoint/transition authorization in §2.1 + §3 + §4; all four roles' `identity: opaque` translated into §2.1 prose; SoD chain rendered in §2.11

### Hard Contract reports
- **Contract 1 (Field-Name Coverage):** entities[].fields: 77 required, 77 present, 0 missing; request_body: 53 required, 53 present, 0 missing; query_params: 0 required, 0 present, 0 missing; path_params: 13 required, 13 present, 0 missing. (Two passes run — first pass caught `stop_id`/`track_id` FK fields and all 13 path-param identifiers missing; repaired in §2.7; second pass clean.) All 47 state/enum values, all 34 error IDs, all 4 role names verified present. **Status: PASS**
- **Contract 2 (Rule Coverage):** validations with priority: 33 checked, 33 expressed; concurrency_rules OCC rejections: 2 checked, 2 expressed (write endpoint + `expected_tour_version`/`expected_stop_version` + `ERR_STALE_VERSION`/412 all named, no time-overlap framing); state-machine transitions: all checked and fully expressed across 11 machines; calculations: 8 checked, 8 fully expressed; validation conditions: all matchable to error IDs in prose; endpoint side effects / applies_to scopes: all expressed; field-level structured content (defaults, nullability, snapshots, computed-field semantics): reconstructible from prose; sibling-branch symmetry: COVERED/REPLACED, pre/post-recoupment rate cards, per-diem variants, all six tech-check transitions rendered with equal density. **Status: PASS**
- **Contract 3 (§3 Path Purity):** 458 backtick tokens scanned in §3; tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path combined: 0. **Status: PASS**

**Zero-Silence Rule confirmation:** Every scaffold behavior — all 77 entity fields with their constraints/defaults/sources, all state transitions with preconditions and side effects, all 8 calculations with constants (6%/9%/8%/11% royalty rates, 8/4/double-time OT tiers, 24-hour cancellation window, 120-minute curtain gap, 8-show weekly/2-show daily caps, 31–60/≤30-day penalty bands), both OCC rules, all 33 validations with their priority ordering and applies_to scopes, all 41 endpoints, all 34 errors, and all 4 roles — appears as PRD prose. Nothing was invented; nothing was omitted.

## Step 5: Generate Unit Tests — 2026-08-15T04:32:44.257Z

Generation complete. All artifacts live under `/home/ubuntu/github/CodingPRD/tasks/task_1957_touring_theatrical_company_management/`.

## Deliverables

**test_helpers/ — 9 files** (Stage 1)
- `types.py` — 12 entity TypedDicts + 15 status/type enums (all entities carry `common_fields: true`, so all include `id`/`created_at`/`updated_at`/`version` per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (41 endpoints)
- `api_errors.py` — all 34 PRD §5 error IDs with HTTP statuses, registered via `set_error_http_status_map` at import
- `assertions.py` — per-entity `assert_*` plus `assert_budget_identity` (PRD §3.1 invariant)
- `factories.py`, `constants.py` (royalty bps, caps, tier boundaries, default logical clock), `test_users.py` (4 opaque roles + per-user builders for the SoD custody chain)
- `fixtures.py` — 5-tier composite helpers (`setup_ready_stop`, `setup_closed_stop_with_settlement`, `setup_submitted/approved/paid_settlement`, `setup_wrapped_stop`, `setup_principal_with_understudy`, etc.); OCC versions always read fresh, never assumed
- `__init__.py` — barrel export

**test_suite/ — 11 files, 101 tests** (Stage 2), all collected cleanly by pytest with real imports:
`test_01` tours/venues/envelope (7), `test_02` routing/windows/OCC/amend (11), `test_03` tech checks/certification (8), `test_04` performances (12), `test_05` settlements/royalty/SoD (16), `test_06` wrap/budget/cancellation (13), `test_07` cast/coverage/injury (16), `test_08` per-diems (7), `test_09` crew calls (6), `test_10` RBAC/listing/clock (5).

## Coverage

- **Queue A (Difficulty): 24/24 instances, exactly 2 tests each = 48 tests.** All instances passed the PRD-first filter — no skips.
- **Queue B (Corner): 53/53 non-stub instances = 53 tests.** All 19 `excluded_because:` stubs verified to resolve to real queue-A instances and not translated.

## PRD-first adjudications worth noting

1. `weekly_cap_eighth_ok_ninth_fails` — the recipe's literal 9th-show placement (third show on Sunday) violates both weekly and daily caps, and PRD does not pin intra-priority-6 ordering. The 9th show was placed on a singly-occupied day with a legal curtain gap so `ERR_WEEKLY_SHOW_CAP` is uniquely derivable.
2. `second_open_injury_returns_duplicate_record` — a COVERED injury always implies ON_LEAVE, so the pinned pipeline (state p5 before uniqueness p7) and §3.10's "a second report drawing ERR_DUPLICATE_RECORD" conflict. Per the error-precedence silence pattern the test uses `validate_error_is_one_of([ERR_DUPLICATE_RECORD, ERR_CAST_INVALID_STATE])`.
3. `tour_create_defaults_and_roundtrip` / `stop_create_initial_state` — the `version == 1` sub-assertion is not PRD-derivable (§2.4 pins increment-by-one but not the initial value); those tests assert integer type plus relative increments instead. Everything else in those instances is asserted verbatim.

## Contract verification

- Automated audit (AST-based): every test's docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line resolving to a real non-stub instance; queue coverage complete; zero untagged/dual-tagged/stub-tagged tests.
- Citation audit: every ≥8-word citation span verified **fully verbatim** (whitespace-normalized, exact apostrophes) against `workspace/PRD.md` — 50 straight-vs-curly apostrophe mismatches found and repaired against the PRD's exact characters; final strict pass: 0 failures.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold" references in generated code; no freelance tests beyond the two design indices.

## Step 6: Generate Implementation — 2026-08-15T04:32:44.257Z

Implementation complete and verified. Summary:

## File list — `tasks/task_1957_touring_theatrical_company_management/workspace/implementation/`

| File | Contents |
|---|---|
| `start.sh` | Executable launcher: guarded dep install (`if ! python3 -c "import flask"`), `exec python3 app.py` in foreground |
| `requirements.txt` | `flask>=3.0` |
| `app.py` | Flask entry point; blueprint registration; envelope error handlers (ApiError, 404/405, fallback); `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))` |
| `db.py` | In-memory dict stores (12 collections, keyed by id, **empty on every boot — no seeding**), UUID ids, ISO-8601 3-fractional-digit timestamps, `version` starting at 1 with `touch()` on every mutation incl. cascades, monotonic insertion seq, logical clock defaulting to exactly `2026-08-01T00:00:00Z` |
| `errors.py` | `ApiError` + all 33 error IDs verbatim from the catalog |
| `response.py` | Envelope: `meta{api_request_id, api_request_timestamp}` + `response_type` + `data`; list responses add `limit/offset/total_count/has_more` |
| `middleware.py` | `X-User-Role` auth (401 `ERR_UNAUTHENTICATED`), per-endpoint/transition role gates (403 `ERR_FORBIDDEN`); `X-User-ID` opaque, recorded for SoD only |
| `util.py` | Shape validators (unknown-field rejection, typed ints/numbers/enums/dates, `HH:MM` curtain), `Decimal`+`ROUND_HALF_UP` money helpers, pagination (limit default 10, clamped 1..100; offset default 0) |
| `services/calc.py` | All 8 calculations with pinned rounding: provisional estimate, settlement waterfall (taxes→levies→guarantee-vs-split, only step 2 rounds), marginal royalty (600/900 pre, 800/1100 post, per-bracket rounding), per-diem (FULL_WEEK / ACTUAL_DAYS with half-rate rounded first), bump pay (salary/8 rhu), crew pay (8h/1.5x 4h/2x, round once per line), crew + stop cancellation penalties (24h and 60/31/30-day boundaries verified) |
| `services/domain.py` | Derived-state recompute (compliance_status, available_covers/exposed) and cascades: certification revoke (READY→ADVANCED on FAIL), stop auto-close + DRAFT settlement auto-create, weekly wrap (budget buckets, recoup flip AFTER totals post), stop cancel cascade (performances, crew calls, penalties into budget_spent), injury fork (COVERED with selector / REPLACED fallback), injury resolve |
| `routes/*.py` | 13 blueprints |

## Endpoints
All **42 routes** from the endpoint table (41 resource endpoints + `POST /_clock/set_current_utc`), including shared-transition endpoints with per-transition role gates (Producer-only CONTRACTED/WRAPPED/CANCELLED/waive/dispute/void; TourManager-only ADVANCED/READY/measurements/cancel-perf/crew; Treasurer-only PLAYED/figures/SUBMITTED; APPROVED/PAID shared with SoD).

## State machines / validations / OCC
- 10 state machines implemented with exact source-state guards and side effects; cyclic Settlement (DISPUTED→SUBMITTED re-arms SoD), branching InjuryEvent (fork decided atomically at creation), parallel Stop booking×compliance dimensions.
- Validation pipeline ordered per PRD §2.8: auth (401/403 incl. SoD) → existence (404, path left-to-right + body FKs) → shape (400, incl. `ERR_PER_DIEM_INVALID` and `ERR_WAIVER_NOTE_REQUIRED` immediately after generic shape) → state (409) → caps (422) → uniqueness (422) → temporal (422) → referential (422) → fiscal (422).
- OCC: `expected_tour_version` on stop create and `expected_stop_version` on amend — required fields, mismatch → 412 `ERR_STALE_VERSION`; both counters advance on every direct and cascade mutation.

## Boot contract
Confirmed: `bash start.sh` boots in the foreground on `$PORT`/`0.0.0.0`, HTTP-ready in ~2s, store empty, clock at the PRD default. Two ad-hoc suites (55+ assertions each — full lifecycle plus boundary/edge cases: 61/60/30-day penalty bands, 24h crew-cancel boundary, weekly/daily caps, curtain-gap equality, recoup flip timing across two wraps, marginal royalty above threshold, dark-week settlement, bump-pay accrual, dispute/resubmit SoD re-arming) both pass on a fresh boot; `pyflakes` clean.

## Step 7: Run Tests and Iterate — 2026-08-15T04:42:22.645Z

**Exit condition met: all 8 parallel rounds pass — 101/101 tests in every round (808/808 total), zero failures, zero flakiness across the union.** (Orchestrator re-verified all 8 `results.{i}.json` files on disk: 101/101, 0 failed, every round.)

- **Iterations run:** 2 (initial sweep surfaced 3 consistent failures; fixes applied; verification sweep clean).

- **Tests deleted:** none. Every failing test traced to a PRD-verbatim rule with unique derivability; no PRD-silence or collapse-pattern deletions were warranted.

- **Fixes applied to `test_helpers/`:** none — fixtures, factories, role headers, and assertion helpers were all PRD-faithful.

- **Fixes applied to `test_suite/`** (all in `/home/ubuntu/github/CodingPRD/tasks/task_1957_touring_theatrical_company_management/test_suite/test_04_performances.py`, all STEP-2 test bugs where the test's own setup/arithmetic contradicted the PRD rule it asserted):
  1. `test_performance_schedule_on_ready_and_playing_ok` — asserted the stop stays `PLAYING` after playing its *only* performance. PRD §3.4's auto-close rule ("when every performance of the stop has resolved … the stop closes") fires in the same request, so `CLOSED` is the PRD-correct outcome. Fixed by scheduling a second still-`SCHEDULED` performance before the play so `PLAYING` is observable, then verifying scheduling on the `PLAYING` stop with a third performance.
  2. `test_curtain_gap_exact_equality_passes` — used curtain 16:50 as the "equality" point for a 14:00 show with 150-minute duration; the true equality point is 14:00 + 150 + 120 = 18:30. Fixed curtain_time to `18:30`.
  3. `test_daily_cap_third_show_returns_error` — setup's second show at 14:00 violated the curtain gap (12:00 + 60 + 120 = 15:00, not 14:00), so setup itself failed before the daily-cap assertion. Fixed times to 12:00/15:00 with the third show at gap-legal 17:00.

- **Fixes applied to `implementation/`:** none — the implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1957_touring_theatrical_company_management/workspace/implementation/` was PRD-faithful in every failure (correctly rejecting the gap-violating requests and correctly auto-closing the fully-resolved stop).

## Step 8: Finalize PRD — 2026-08-15T04:47:42.795Z

Analysis complete. PRD_FINALIZED.md is byte-identical to PRD.md — the correct minimal patch is the empty patch. Here is the full report.

## Summary on exit

**Line counts / delta:** PRD.md = 318 lines; PRD_FINALIZED.md = 318 lines; 0% delta (byte-identical, `diff` clean).

**Changes:** none. All three `<step_7_diff>` items are STEP-2 test bugs at sites where the PRD already uniquely determines the behavior and `implementation/` is PRD-faithful. There were no implementation fixes, no test deletions, and no `test_helpers/` fixes in the diff, so there is no PRD-silence or PRD-mismatch to pin. Per the method ("not every item is a PRD silence (some are pure fixture bugs)"), each item was evaluated and rejected as an edit trigger:

- **§3.4 auto-close timing** (`test_performance_schedule_on_ready_and_playing_ok`) — PRD §3.4 ("when every performance of the stop has resolved … the stop closes" and auto-creates the `DRAFT` settlement), §2.10 ("closing a stop and auto-creating its settlement when its final performance resolves"), and §2.4 (automatic transitions are real mutations) uniquely pin a synchronous close on the marking request. Impl `routes/performances.py:164,168` calls `services/domain.py:96-123` (`auto_close_stop_if_resolved`) inline in the PUT; with one performance, playing it resolves all, so `CLOSED` is the only PRD-consistent outcome. The fixed test's added second still-`SCHEDULED` performance is exactly what makes `PLAYING` observable — pure test bug, no edit.
- **§3.4 curtain-gap equality** (`test_curtain_gap_exact_equality_passes`) — PRD verbatim: "equality passes". Impl `routes/performances.py:66-76` rejects only on strict `<` against `earlier_curtain + duration_minutes + 120` in both directions; 14:00 + 150 + 120 = 18:30 is the true equality point the fixed test now uses. Pure arithmetic bug in the old test (16:50), no edit.
- **§3.4 daily cap** (`test_daily_cap_third_show_returns_error`) — PRD verbatim: "a third performance on the same `perf_date` is rejected with `ERR_DAILY_SHOW_CAP`". Impl `routes/performances.py:58-61` enforces `len(same_day) >= 2` at priority 6, before the priority-8 gap check. The old test's setup itself violated the curtain gap (12:00 + 60 + 120 = 15:00, not 14:00); the fixed 12:00/15:00/17:00 setup is gap-legal. Pure fixture bug, no edit.

**Per-edit pre-edit search log (three candidate edits evaluated; none committed):**

1. (a) Subject: stop auto-close synchronous timing + settlement auto-creation. (b) Enumerated paths: `implementation/routes/performances.py:104-169` (PUT mark PLAYED/CANCELLED, both branches call auto-close), `implementation/services/domain.py:96-123` (close guard on READY/PLAYING, `system_gross_cents` = sum over PLAYED only, dark-week 0), `implementation/services/domain.py:152-187` (`cancel_stop` cascade — does *not* call auto-close; sets performances `CANCELLED` directly and stop `CANCELLED`, so no CLOSED/CANCELLED conflict), `implementation/routes/stops.py:218-222` (cancel route). PRD §2.4, §2.10, §3.4 re-read. (c) No wording change — PRD already uniquely determines every enumerated path; any edit risked a false universal claim (NO-NEW-MISMATCH).
2. (a) Subject: curtain-gap rule (boundary semantics, directionality, status scope). (b) Enumerated paths: `implementation/routes/performances.py:50-76` (`live` = SCHEDULED/PLAYED filter feeding weekly cap, daily cap, and gap loop; symmetric later/earlier branches; equal-curtain case falls into the "new is later" branch and always rejects, consistent with duration ≥ 1); `implementation/util.py:114-119` (`parse_curtain` to minutes). (c) No wording change — "equality passes" is PRD-verbatim and matches the strict-`<` rejection; I additionally considered pinning the impl's SCHEDULED/PLAYED scoping of the gap/cap sibling sets but no step_7_diff fix revealed that question (no test exercises CANCELLED-perf interaction), so the hard scope forbids the edit.
3. (a) Subject: daily-cap counting rule and pipeline position. (b) Enumerated paths: `implementation/routes/performances.py:51-61` (weekly cap then daily cap, both over `live`; priority 6 before temporal priority 8 per PRD §2.8), test_suite/test_04_performances.py:66-187 (all four cap/gap tests re-read). (c) No wording change — PRD verbatim matches impl; same scoping consideration as (2), same conclusion.

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_1957_touring_theatrical_company_management/workspace/PRD_FINALIZED.md` (318 lines, identical to PRD.md).

## Step 9: Complete PRD — 2026-08-15T05:05:45.776Z

All edits are applied and verified against the implementation. The full diff corresponds exactly to the 23 edit operations I intended (some carrying multiple pins). Final verification of counts:

- Source: `PRD_FINALIZED.md` (318 lines, 51,280 chars); `PRD_COMPLETED.md` (320 lines, 56,175 chars) — delta **+2 lines, +4,895 chars**.

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1957_touring_theatrical_company_management/workspace/PRD_COMPLETED.md` (copied from `PRD_FINALIZED.md`, then edited in place; 23 edit operations).

**Counts:** 28 ambiguity-pins, 4 mismatch-revisions (32 distinct pinned behaviors total; no new sections added, all changes are in-paragraph inserts/revisions).

**Mismatch revisions (4):**
- §2.1 — revise — mismatch — PRD said every request "must carry" both headers; impl only enforces `X-User-Role` and never rejects a missing `X-User-ID` — `implementation/middleware.py:18-22`
- §2.8 — revise — mismatch — PRD said SoD checks run "before any existence or state question"; impl resolves the settlement first (404 precedes SoD), then SoD before shape/state — `implementation/routes/settlements.py:69-80`
- §3.7 — revise — mismatch — PRD said figures-only writes "change nothing else"; impl recomputes waterfall outputs on a figures-only PUT once all three figures are present — `implementation/routes/settlements.py:140-143`
- §3.9 — revise — mismatch — on `PATCH /tracks/{id}` impl runs shape checks (presence/type of `principal_member_id`) before resolving member existence, contrary to §2.8's existence-before-shape order — `implementation/routes/tracks.py:114-118`

**Ambiguity pins (28):**
- §2.2 — insert — ambiguity — undefined path / unsupported method → `ERR_NOT_FOUND` (404) in the standard envelope — `implementation/app.py:25-31`
- §2.3 — revise — ambiguity — out-of-range `limit`/`offset` are clamped (limit to [1,100], offset to ≥0), not rejected — `implementation/util.py:137,143`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST` — `implementation/util.py:132-143`
- §2.3 — insert — ambiguity — `has_more` is true exactly when `offset` + returned-count < `total_count` — `implementation/response.py:36`
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — `implementation/db.py:58`
- §2.4 — insert — ambiguity — later-filled fields are null until set (stop `estimated_venue_payment_cents`/`wrapped_total_cents`, performance `gross_cents`, check `actual_value`/`waiver_note`, settlement figures/outputs/audit fields, crew-call `actual_lines`/`total_pay_cents`/`cancellation_penalty_cents`, injury `covered_by_coverage_id` on REPLACED, unassigned `principal_member_id`); stop `cancellation_penalty_cents` initializes to 0 — `implementation/db.py:114-121`, `implementation/routes/stops.py:122-124`
- §2.5 — insert — ambiguity — offset-less ISO datetimes (`scheduled_start`, `to_iso8601`) interpreted as UTC — `implementation/util.py:109-110`
- §2.8 — insert — ambiguity — OCC check (`ERR_STALE_VERSION`) slots between shape (p4) and state guards (p5) — `implementation/routes/stops.py:88-91,258-261`
- §2.8 — insert — ambiguity — accepted-but-inapplicable fields are ignored, not rejected (`gross_cents` on cancellation, `actual_value`/`waiver_note` on the opposite check op, `dispute_reason` without DISPUTED) — `implementation/routes/performances.py:119,165-168`, `tech_checks.py:79-99`, `settlements.py:83`
- §2.9 — insert — ambiguity — clock response echoes the supplied `to_iso8601` verbatim as `current_utc` — `implementation/routes/clock.py:27-28`
- §3.2 — insert — ambiguity — contracting against a tour not in PLANNING/ON_TOUR → `ERR_STOP_INVALID_STATE` — `implementation/routes/stops.py:180-182`
- §3.2 — insert — ambiguity — requesting TENTATIVE/PLAYING/CLOSED as a booking_status target → `ERR_STOP_INVALID_STATE` — `implementation/routes/stops.py:223-226`
- §3.3 — insert — ambiguity — an empty `waiver_note` is treated as absent (`ERR_WAIVER_NOTE_REQUIRED`) — `implementation/routes/tech_checks.py:88-91`
- §3.4 — revise — ambiguity — daily cap and curtain-gap check consider only SCHEDULED/PLAYED performances — `implementation/routes/performances.py:51,58,66`
- §3.4 — insert — ambiguity — stop-state gate evaluated before the performance-state guard; requesting SCHEDULED as a target → `ERR_PERFORMANCE_INVALID_STATE` — `implementation/routes/performances.py:125-135`
- §3.4 — insert — ambiguity — a marking that is both first-played and final-resolution moves the stop READY→PLAYING→CLOSED as two mutations (version +2) — `implementation/routes/performances.py:143-164`, `implementation/services/domain.py:96-105`
- §3.5 — revise — ambiguity — every satisfied CREW_MINIMUM check (if several) floors the line count — `implementation/routes/crew_calls.py:91-95`
- §3.5 — insert — ambiguity — `hours_worked` is a non-negative number, fractional hours allowed — `implementation/routes/crew_calls.py:57-59`
- §3.5 — insert — ambiguity — requesting a transition back to POSTED → `ERR_CREW_INVALID_STATE` — `implementation/routes/crew_calls.py:135-136`
- §3.6 — insert — ambiguity — per-diem `cast_member_id` must exist only; no contract-status or same-tour condition enforced — `implementation/routes/per_diems.py:27-38`
- §3.6 — revise — ambiguity — `travel_days` floored at 0 (range 0..min(2, days_present) inclusive) — `implementation/routes/per_diems.py:48`
- §3.6 — insert — ambiguity — requesting any status other than PAID → `ERR_PER_DIEM_INVALID_STATE` — `implementation/routes/per_diems.py:109-111`
- §3.7 — insert — ambiguity — figure writes outside DRAFT/DISPUTED → `ERR_SETTLEMENT_INVALID_STATE` — `implementation/routes/settlements.py:100-102`
- §3.7 — insert — ambiguity — figures may accompany SUBMITTED (applied before completeness check); figure+status combos are Treasurer-only, so figures+DISPUTED/VOID always → `ERR_FORBIDDEN` — `implementation/routes/settlements.py:54-67,113-124`
- §3.7 — insert — ambiguity — a settlement PUT with neither figures nor `status` → `ERR_INVALID_REQUEST` — `implementation/routes/settlements.py:144-146`
- §3.7 — revise — ambiguity — empty `dispute_reason` treated as absent — `implementation/routes/settlements.py:90-94`
- §3.8 — insert — ambiguity — `recouped` is recomputed at every wrap (`cumulative >= capitalization`), so a later negative producer net can flip it back to false — `implementation/services/domain.py:147`
- §3.9 — insert — ambiguity — requesting ON_LEAVE/REPLACED directly → `ERR_CAST_INVALID_STATE` — `implementation/routes/cast.py:109-111`
- §3.9 — revise — ambiguity — any coverage-endpoint request other than releasing a STANDBY coverage (wrong target, or coverage ACTIVATED/SUSPENDED/RELEASED) → `ERR_COVERAGE_ACTIVATED` — `implementation/routes/coverages.py:106-108`
- §3.9 — insert — ambiguity — releasing a member does not clear `principal_member_id` on any track — `implementation/routes/cast.py:98-108`
- §3.10 — insert — ambiguity — injury `notes` defaults to an empty string — `implementation/routes/injuries.py:29`
- §4 — revise — ambiguity — `GET /stops` `status` filter matches `booking_status` — `implementation/routes/stops.py:143-144`

**Coverage note:** all 40 routes, every state-machine transition, every calculation (waterfall, royalty brackets, crew pay tiers, per-diem variants, cancellation penalties, bump unit), every validation/ordering rule, every cascade side effect, and every error code in `implementation/` were walked against the PRD; behaviors already uniquely pinned (window-conflict math, cap numbers, royalty rates, SoD re-arm, selector tie-breaks, freeze-at-certification, etc.) were left untouched.
