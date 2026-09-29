# Worklog — task_2220_roadside_inspection_data_review_challenge

## Step 1: Create task directory — 2026-09-01T05:33:17.873Z

Created `tasks/task_2220_roadside_inspection_data_review_challenge/` and `tasks/task_2220_roadside_inspection_data_review_challenge/workspace/` (pre-allocated name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T07:32:32.805Z

All three scaffold artifacts for scenario 2220 are complete and lint-clean.

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2220_roadside_inspection_data_review_challenge/`):
- `SCAFFOLD.yaml` (§1.0–§1.7, 2902 lines) — no `scaffold_difficulty_design` / `scaffold_corner_design` keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`, 2774 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`, 5334 lines)

Counts
- §1.1–§1.7: 15 entities, 6 state machines (cyclic primary; branching/parallel/compound/guarded secondary), 3 OCC concurrency rules, 7 calculations, 34 priority-ordered validations, 61 endpoints, 61 error codes, 5 roles (`segregation_of_duties`), `consistency_model: immediate`, `difficulty_level: beyond_expert`.
- §1.8: 9 difficulty rules / 25 instances (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- §1.9: all 9 sections / 85 instances = 56 full test recipes + 29 `excluded_because` stubs — entities 10, state_machines 18 (11+7), calculations 11 (6+5), validations 15 (12+3), endpoints 6, errors 10 (all stubs), rbac 5, cross_cutting_complexity_layers 9 (5+4), consistency_model 1.

Cross-checks run beyond the linter: every stub's `difficulty_instance` citation resolves to a real §1.8 rule/instance pair; instance names are unique across both design files; forbidden race vocabulary ("simultaneously" etc.) removed from all three files; corrected a stale count in `difficulty_notes` (it said "34 error codes"; 34 is the validation-rule count, errors are 61).

Verdict block, verbatim from the final run of `python3 /home/ubuntu/github/CodingPRD/skills/prd-bench-scaffold-generator/scaffold_lint.py`:

```
Coverage
  §1.5 endpoints declared:    61
  §1.1 entities declared:     15
  §1.8 instances scanned:     25
  §1.9 instances scanned:     56
  Calls scanned (§1.8+§1.9):  1086

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Step 3: Copy shared files — 2026-09-01T07:32:32.805Z

Copied `INSTRUCTION.md` from project root to `tasks/task_2220_roadside_inspection_data_review_challenge/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T07:48:16.693Z

PRD complete and audited.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2220_roadside_inspection_data_review_challenge/workspace/PRD.md` — **524 lines, 13,845 words**

## Sections covered
- **§1 Introduction** — 3 paragraphs (data-quality pain points → what the system holds → design constraints)
- **§2 Global Specifications** (11 subsections, domain-derived rather than template-copied): 2.1 RBAC & identity translation for all 5 roles · 2.2 Response Structure (byte-verbatim) · 2.3 Pagination · 2.4 Logical Clock & Scoring Epoch · 2.5 Common Record Properties (incl. the two `common_fields: false` entities) · 2.6 Optimistic Concurrency (all 3 rules) · 2.7 Numeric Precision & Rounding · 2.8 Order of Evaluation (full 1–34 precedence list with scopes) · 2.9 Reference Resolution & Nested Reads · 2.10 The Recomputation Cascade · 2.11 Segregation of Duties
- **§3 Business Logic** (11 subsections): 3.1 Carriers/fleet bands/drivers/reference data · 3.2 Report intake · 3.3 Severity & time-weight pinning · 3.4 Measures, percentiles, intervention posture · 3.5 Screening risk & data-quality credit · 3.6 Data-challenge lifecycle (all 4 accept cascades) · 3.7 Amendments · 3.8 Citations, court results, record updates (dual state dimensions) · 3.9 Driver attribution & coaching · 3.10 Safety fitness & CAPs · 3.11 Scoring-run checkpoint
- **§4 Endpoint Definitions** — 1 intro paragraph + 61-row table, exactly 4 columns
- **§5 Error Code Catalogue** — 61-row table, exactly 2 columns. File ends here; no audit footer.

## Hard Contract audits

**Contract 1 — Field-Name Coverage: PASS.** Machine-checked twice against a 177-name required set derived from `entities[].fields[].name` (157), non-GET endpoint `input` (73), GET `input` query params (41) and endpoint `output` keys (17). Pass 1 found 2 gaps (`cap_id`, `challenge_id`); both were added in prose (§3.6 evidence, §3.10 action items). Pass 2: **177/177 present in backticks, 0 missing.**

**Contract 2 — Rule Coverage: PASS.** All six high-risk categories emitted: (1) full 34-step validation precedence in §2.8 with each `applies_to` scope; (2) all three `concurrency_rules` with exact expected-version fields and 412 error IDs, plus the explicit "no other endpoint takes a version field" statement; (3) all cross-entity cascades spelled out per trigger (challenge accept ×4, rescission, amendment, apply-to-record, attribution clear, all coaching waivers); (4) scoped validations; (5) field-level structured content — every enum value across all 15 entities verified present (only the internal constant *names* `COACHING_TRIGGER`/`MAX_INFO_ROUNDS` are absent, deliberately, with their values 12.0 and 3 stated in prose); (6) sibling-branch symmetry — `VALIDATED` vs `SCORED` recompute asymmetry, withdraw from all three states, all four accept dispositions, all three `apply-to-record` branches incl. `NOT_APPLICABLE`. Tail: all 46 state transitions describable with both endpoint states named, all 7 calculations with all constants, all 34 validation conditions (all 61 error IDs appear in §1–§3 prose, not just the §5 table), all endpoint `side_effects`.

**Contract 3 — §3 Path Purity: PASS.** 347 distinct backticked tokens in §3 scanned: **0** begin with `/`, **0** are a bare HTTP method, **0** are a method+path combination. Endpoints referenced only via state-transition framing, role + action verb, or capability description.

**Other checks:** §4 table matches the scaffold's 61 endpoints exactly (0 missing, 0 extra, methods and paths identical). §5 matches the 61 errors exactly with 0 status-code mismatches. §2.2 is byte-verbatim. No fuzzy words (`approximately`/`roughly`/`conservatively`/`about`/`around`/`~`), no pseudocode, no sentinels left in the file.

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped or referenced, and no sibling task directory was inspected.

## Step 5: Generate unit tests — 2026-09-01T09:29:07.251Z

All 17 files are written and both gates are clean.

## Deliverables

**`test_helpers/`** (Stage 1, complete): `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`
**`test_suite/`** (Stage 2): `conftest.py` plus `test_01_dual_variant_calc.py` … `test_17_consistency_model.py`

Files written this session: `test_15_rbac.py` (5), `test_16_cross_cutting_complexity_layers.py` (5), `test_17_consistency_model.py` (1); `test_14_endpoints.py` touched to route `category_contributions` through the shape-tolerant `contribution_for` helper.

## Counts

- **105 tests**, all collected by `pytest --collect-only`; `py_compile` clean; no unused imports; no "scaffold" mentions anywhere.
- **Queue A (Difficulty §1.8): 25/25 instances, 50 tests, 0 skips** — files 01–09.
- **Queue B (Corner §1.9): 55/56 non-stub instances, 55 tests, 1 skip** — entities 9/10, state_machines 11/11, calculations 6/6, validations 12/12, endpoints 6/6, rbac 5/5, cross_cutting_complexity_layers 5/5, consistency_model 1/1.
- Every test carries exactly one verbatim `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` final docstring line plus a ≥40-char verbatim PRD quote (checked by AST gate: 105 tests / 0 problems).

## Skipped (gaps left as gaps)

- `Corner/entities/computed_and_system_fields_on_create_input_ignored` — the PRD never says client-supplied computed/system fields are ignored on create, so the asserted outcome is not uniquely derived. No placeholder emitted.
- All `errors`-section instances were `excluded_because:` stubs and were never eligible.

## Design assertions deliberately dropped (instance still translated)

- `validations/scoring_without_a_configured_threshold_rejected`: dropped the "`POST /scoring-runs` → 409 `ERR_THRESHOLD_NOT_CONFIGURED`" probe. PRD §3.4 includes only violations whose owning report is `SCORED`, and §3.11's sweep errors only when a category holds an includable violation — the run would succeed. The per-report score probes and success path are kept.
- `rbac/cap_decision_by_the_fitness_determiner_rejected`: dropped `Carrier.version == c1_version + 1`; §3.10 bumps the carrier on both plan creation and the ACCEPT upgrade (+2). Asserted `safety_fitness_status == SATISFACTORY` instead.
- `consistency_model/score_response_and_immediate_reads_agree_without_a_scoring_run`: the design asserts `intervention_status == MONITOR`, which is not an `InterventionStatus` value; asserted the PRD-derived `NONE` (§3.4 roll-up: `open_alert_count` 0). Also dropped "GET /scoring-runs total_count 0" (§4 exposes no scoring-run list endpoint) and the Violation-level `severity_basis_utc` check (a report field) — both covered by `scoring_run_id is None` on all four rows.
- Earlier files: `factor_breakdown` sub-field names (PRD fixes only the entry count) and any `scores_updated` assertion on a scoring run.

## Step 6: Generate implementation — 2026-09-01T09:29:07.251Z

Implementation complete and verified.

## Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_2220_roadside_inspection_data_review_challenge/workspace/implementation/` (3,768 lines total):

- `start.sh` (executable), `requirements.txt` (`flask>=3.0`)
- `app.py` — factory, blueprint registration, snapshot/restore atomicity hooks, error handlers, `0.0.0.0:$PORT` (default 10000), `threaded=False`, no reloader
- `db.py` — in-memory `Store` (15 dicts keyed by id), logical clock fixed at `2026-08-01T00:00:00Z`, `TS` wrapper, snapshot/restore, `serialize`, `touch`
- `errors.py` — 63 error ids with statuses + message fallbacks; `response.py` — envelope/pagination; `middleware.py` — auth + carrier scoping; `validation.py` — shape/enum/range/pagination helpers
- `services/calc.py` (constants, ROUND_HALF_UP helpers), `services/cascade.py` (severity pin, report rollup, BasicScore rows, posture, screening risk, driver aggregates, coaching waivers, challenge coverage), `services/runs.py` (six-sweep scoring-run checkpoint)
- `routes/reference.py` (21), `routes/reports.py` (13), `routes/challenges.py` (13), `routes/plans.py` (14), `routes/helpers.py`

## Verification
- **Endpoints: 61/61.** A static cross-check against `SCAFFOLD.yaml` reports `missing: [] extra: [] role mismatches: 0` (method, path and allowed-role set all match).
- **Entity fields: 15/15 exact.** Live serialized keys equal the scaffold field list plus common fields for every entity (`ReportAmendment`/`ChallengeEvidence` correctly carry only `id`/`created_at`).
- **Three end-to-end smoke suites, 0 failures:** core flow (register → ingest → validate → score → basic-scores/screening-risk → challenge → adjudication → coaching → CAP fork-join/decision → scoring run → clock); correction flows (code-correction amendment + `SCORED→AMENDED→SCORED` re-score, attribution set/clear with waivers, WRONG_CARRIER reattribution across two carriers, DUPLICATE_REPORT rescission, info-request round + expiry sweep, coaching OVERDUE→ESCALATED across two runs, driver termination waiver, quota fill/withdraw/re-derive); and guard rails (`ERR_THRESHOLD_NOT_CONFIGURED` 409 with full rollback — report stays `VALIDATED`, no score rows, violation unpinned; `ERR_OOS_REMOVAL_REQUIRES_ADJUDICATION` then success after a dismissal; all three OCC 412s; 401/403/404/400).
- `bash start.sh` boots from a fresh process and serves requests: `GET /carriers` → 200 with an empty array (no seeded data), `POST /carriers` → 201 with all derived fields initialised (`SMALL`, quota 1, utilization 1.2, `UNRATED`/`NONE`/`PASS`).

## Two defects found and fixed during verification
1. `routes/reports.py` — a `VIOLATION_CODE_CORRECTION` amendment did not re-pin the severity snapshot (PRD §2.9: code-correction amendments are one of the three re-pin side effects). It now updates `basic_category` and re-pins `code_weight_snapshot`/`oos_add_on_snapshot`/`pinned_violation_code_version`/`time_weighted_severity` from the new code using the report's `severity_basis_utc`, but only for violations already pinned by a prior scoring pass.
2. `errors.py` — error ids raised without an explicit message (e.g. `ERR_THRESHOLD_NOT_CONFIGURED`, all 404s) echoed the id as the message; added a `_humanise()` fallback.

No SQLite, no JSON dumps, no seeded entities; all background servers used for testing have been stopped and `__pycache__` removed (`start.sh` exports `PYTHONDONTWRITEBYTECODE=1`).

## Step 7: Run tests and iterate — 2026-09-01T09:58:00.000Z

All 8 parallel rounds are green. Final sweep: `105 passed / 105` in every round, 0 failed, 0 errors, 0 skipped, identical across rounds (no flakiness).

## Summary

**Iterations run: 3 sweeps** (8 rounds each) — iteration 1: 71/105 (identical in all 8 rounds); iteration 2: 100/105 (identical); iteration 3: **105/105 in all 8 rounds**.

**Tests deleted: none.** Every failure traced either to a test-layer artifact contradicting a verbatim PRD sentence (STEP 2) or to a missing PRD-required behaviour in the implementation (STEP 3). No assertion was weakened, no skip/xfail added, no error_id downgraded.

**Fixes to `test_helpers/`: none** — all test-layer defects lived in `test_suite/`.

**Fixes to `test_suite/`** (each makes the test *more* faithful to PRD):
- 9 files (`test_07`, `test_08`, `test_10`, `test_11`, `test_13`, `test_14`, `test_15`, `test_16`, `test_17`), **29 sites**: removed the trailing `["data"]` from `validate_success(...)["data"]` — the runner's `validate_success` already returns `body["data"]`, so every site double-indexed (`KeyError: 'data'`). This was the ≥5-shared-error cluster the triage hint predicted.
- `test_02_combinatorial_formula.py`, `test_04_transitive_cascade.py` (3 sites): dropped `resolution_disposition=` from `RESOLVE_ACCEPT` calls — PRD §2.8 tier 3 says it is "supplied only on a reject review action" and §3.6 says accept *writes* the type-specific disposition; the response assertions were kept.
- `test_11_state_machines.py` (~line 499): `IMPLEMENT` now issued with `make_carrier_safety_manager_headers` — PRD §3.10 names IMPLEMENT as the safety manager's action, so an analyst legitimately gets 403 and the test could never reach the state rule it cites.
- `test_16_...py` fixture `_violation_attributed_after_the_officer_read_it`: added report-level `driver_id` — PRD §3.2's attribution-completeness gate correctly rejected the DRIVER-unit violation, so the setup itself was PRD-inconsistent.
- `test_12_calculations.py` (5 sites): routed `category_contributions` reads through the existing shape-tolerant `contribution_for(risk, category)` helper — PRD §3.5 names the field but does not fix list-vs-dict shape.
- `test_13_validations.py` (uniqueness probe): duplicate probe now uses `scenario["carrier"]["dot_number"]` instead of hardcoded `"1000001"` — `factories._dot_seq` is a process-global `itertools.count`, so the hardcoded value only collided when the test ran first (passed in isolation, failed in a full run).
- `test_16_...py` (version test): expectations corrected to 3 after validate and 4 after score — PRD §3.3: "Appending recomputes the report's `active_violation_count` and increments the report's `version` by 1", so the append already consumed a bump.
- `test_17_consistency_model.py`: `iss_value_at_selection`/`selection_band_at_selection` now asserted as `0.0`/`PASS` instead of `None` — PRD §3.1 fixes a fresh carrier's `iss_value` at 0.0 and band at `PASS`, and §3.2 snapshots exactly those; `test_10` already asserted the same values.

**Fixes to `implementation/`** (both in `workspace/implementation/routes/reports.py`):
- `set_driver_attribution` — added the missing PRD §3.9 guard rejecting attribution of a `REMOVED` violation with `ERR_VIOLATION_NOT_ACTIVE`, placed before the `ERR_DRIVER_CARRIER_MISMATCH` check to honour §2.8 precedence.
- amendment cascade (`create_amendment`) — for a `CARRIER_REATTRIBUTION` the gaining carrier's four score rows are now minted/recomputed via `cascade.cascade_carrier_id(..., create=True)` using the losing carrier's scoring epoch, per PRD §3.7: "all four rows of the new attributed carrier as well".

Storage remains in-memory dicts only; no seeding, no files, no new endpoints/fields. Scratch diagnostic files (`rt.sh`, `probe.py`, `probe.sh`), `results.*.json`, and `__pycache__` directories were removed.

_Orchestrator note: the Step 7 subagent deleted `results.*.json` on exit; the orchestrator re-ran the same 8-round sweep afterwards to restore `workspace/implementation/results.{1..8}.json` as durable evidence. That independent sweep reported `passed 105 / failed 0 / errors 0 / skipped 0 / total 105` in all 8 rounds._

## Step 8: Finalize PRD — 2026-09-01T10:07:00.000Z

`PRD_FINALIZED.md` is written. Three edits, all in-place sentence revisions.

## Size
- `PRD.md` — 523 lines / 104,861 bytes
- `PRD_FINALIZED.md` — 523 lines / 106,219 bytes
- Line delta: **0.0 %** (0 lines added/removed; 3 lines revised in place, +1,358 bytes = +1.3 % by size)

## Changes
- **§3.5** — revise — pinned the shape of the `category_contributions` breakdown on `GET /carriers/{id}/screening-risk`: an array of exactly four objects in the fixed category order, each carrying `basic_category`, `category_weight`, `contribution`, `percentile`, `alert_status` (last two empty when no score row exists), plus the exact membership rule for `not_enough_data_categories` — `services/cascade.py:447-468`, `routes/reference.py:158-174`
- **§3.7** — revise — pinned that a `CARRIER_REATTRIBUTION` amendment against a `SCORED` report *mints* the gaining carrier's four score rows when it has none, and that both carriers' rows are aged against the basis already stamped on the losing carrier's rows rather than a fresh clock read — `routes/reports.py:362-372`
- **§3.10** — revise — pinned that a mismatched `action`/role on `POST /cap-action-items/{id}/status` yields `ERR_ROLE_NOT_PERMITTED`, decided from the `action` value alone before the item is resolved — `routes/plans.py:26-31, 316-323`

## No-edit rulings (step_7 items that were test-layer artifacts against verbatim PRD)
`["data"]` double-index; `resolution_disposition` on `RESOLVE_ACCEPT` (§2.8 tier 3 verbatim, enforced at `challenges.py:327`); test_16 fixture missing report-level `driver_id` (§3.2 gate verbatim); hardcoded `dot_number`; report `version` = 3-after-validate / 4-after-score (§3.2 and §3.3 each say "+1" verbatim); `iss_value_at_selection` 0.0 / `PASS` (§3.1 + §3.2 verbatim); `set_driver_attribution`'s `ERR_VIOLATION_NOT_ACTIVE` precedence (§3.9 + §2.8 tiers 8/19 verbatim — impl fix restored PRD, no silence).

## Per-edit pre-edit search log

**Edit A — §3.5 `category_contributions`**
- (a) Subject: the shape/ordering/field set of the screening-risk computed read's per-category breakdown and its `not_enough_data_categories` companion.
- (b) Paths enumerated: `services/cascade.py:447` `category_contributions()` (sole producer); both callers — `recompute_screening()` (`cascade.py:478`, consumes only `contribution`) and `routes/reference.py:163` `screening_risk()` (serialises both return values verbatim); `calc.py:5-17` `CATEGORIES`/`CATEGORY_WEIGHT` to confirm the iteration order is a fixed tuple; `recompute_basic_scores` (`cascade.py:251`) to confirm `percentile`/`alert_status` nullability and that rows are lazily created so `score_row()` can return `None`; `test_helpers/assertions.py:386` `contribution_for` (confirms the shape-tolerance Step 7 added, i.e. the silence). Also checked the parallel computed read `attribution-summary`/`factor_breakdown` (`cascade.py:631`) and deliberately left it untouched — not a step_7 item.
- (c) Adjustment: first draft said `not_enough_data_categories` holds "exactly those entries whose contribution was forced to 0.00". A category with `percentile` 0.0 also computes a 0.00 contribution via the *else* branch and is **not** appended to `excluded`, so that wording would have been a false universal. Re-scoped to the three actual exclusion conditions with an explicit "not merely those whose contribution happened to compute to zero".

**Edit B — §3.7 `CARRIER_REATTRIBUTION` amendment cascade**
- (a) Subject: which carriers' score rows an amendment recomputes, whether rows are created for a carrier that has never scored, and which aging basis stamps them.
- (b) Paths enumerated: `routes/reports.py:362-376` (the `was_scored` / not-scored fork, `epoch_for(old_carrier_id)`, `create=True` for both carriers, `recount_carrier_id` on the unscored branch); `cascade.py:501` `epoch_for`; `cascade.py:524` `cascade_carrier` (the `snapshot_ts or epoch_for or now_ts()` fallback chain); `cascade.py:251` `recompute_basic_scores` (the `create` gate, `snapshot_utc` write, `scoring_run_id=None`); every other `cascade_carrier_id` callsite for consistency — `reports.py:223` score pass (live clock, `strict=True`), `challenges.py:428-432` `WRONG_CARRIER` accept (same losing-carrier-epoch pattern, `create=was_scored`), `challenges.py:451/482/497` (no explicit snapshot), `challenges.py:667` apply-to-record, `runs.py:84` (run snapshot); §3.4's "created lazily on the carrier's first scoring event" and §2.4's "on-demand pass uses the live clock".
- (c) Adjustment: scoped the claim to the `SCORED` branch of the amendment only, and said "the basis already stamped on the old attributed carrier's score rows" rather than any general rule about cascades — the `WRONG_CARRIER` accept path and the plain single-carrier cascades use the same idea but with different `create` flags and fallbacks, and §2.4 already assigns the live clock to the explicit score pass. Confirmed `epoch_for(old_carrier_id)` cannot be `None` on this branch (a `SCORED` report implies a completed pass minted the losing carrier's rows, and rows are never deleted), so no fallback caveat was needed.

**Edit C — §3.10 action-item role gate**
- (a) Subject: the consequence of driving an action-item `action` with a role that owns a different action, and where that check sits relative to body validation and path resolution.
- (b) Paths enumerated: `routes/plans.py:314-325` `set_item_status` in full (`actor(...)` three-role allow-list → `get_enum("action")` → `ACTION_ROLE` comparison → `get_or_404` item → `scope`); `plans.py:26-31` `ACTION_ROLE` map; `middleware.py:31-41` `actor()` (the only other `ERR_ROLE_NOT_PERMITTED` source, confirming both share one error id); `errors.py:22` (403 mapping); grepped for any other multi-role write endpoint carrying a per-action role split — only `/inspection-reports/{id}/score` (`reports.py:205`, both roles may run it, no split) and the single-role `/data-challenges/{id}/review`, `/corrective-action-plans/{id}/reviews`, `/decision`, so the mechanism is unique to this endpoint; §2.1's "each role may only drive the transitions named for it in §3.10" and §2.8 tiers 2-4.
- (c) Adjustment (Edit C): dropped an initial reference to "§2.8 tier 2". The impl validates the `action` enum (tier 3) *before* the role comparison, so a request with both a bad `action` and a wrong role returns `ERR_INVALID_REQUEST` — labelling the check as tier 2 would have asserted an ordering the impl does not exhibit. Replaced with the factual, tier-free "follows from the recognised `action` value alone and is reached before the addressed item is resolved", which matches the actual sequencing on both sides.

## Step 9: Complete PRD — 2026-09-01T10:24:19.185Z

All planned edits are applied. Final verification and counts are in.

**File comparison**
- `workspace/PRD_FINALIZED.md` — 523 lines / 106,219 chars
- `workspace/PRD_COMPLETED.md` — 524 lines / 117,319 chars
- Delta: **+1 line, +11,100 chars**; 35 existing lines revised in place, 1 new bullet added to the existing §2.2 error-format list. No new sections, no new paragraphs.

**Counts: 40 changes — 29 ambiguity-pins, 11 mismatch-revisions.**

- §2.1 — insert — ambiguity — extended the carrier-scope field list (`BasicScore.carrier_id`, evidence via its challenge, cap items via their plan, adjudications via the linked violation) and pinned that amendments, scoring runs and reference collections carry no scoping — `implementation/middleware.py:44`
- §2.2 — insert — ambiguity — unknown path or unsupported method reports `ERR_NOT_FOUND` at HTTP 404 — `implementation/app.py:20`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` and unrecognised enum filter values are `ERR_INVALID_REQUEST`; identifier filters match exactly and yield an empty page — `implementation/validation.py:124`
- §2.4 — insert — ambiguity — clock echo normalised to three fractional digits, `to_iso8601` required, backwards moves permitted — `implementation/routes/reference.py:31`
- §2.5 — insert — mismatch — version bumps only when a recompute actually moves a stored value, at most once per request, and created records return at `version` 1 — `implementation/db.py:140`
- §2.7 — insert — ambiguity — client-supplied instants echoed verbatim; only server-minted instants are normalised — `implementation/db.py:32`
- §2.8 (tier 3) — insert — ambiguity — required strings must be non-blank once trimmed, plus the complete per-field length-cap table — `implementation/validation.py:30`
- §2.10 — insert — ambiguity — data-driven cascades reuse the existing score-row basis, mint rows only on the listed paths, and a rejected request rolls back whole — `implementation/services/cascade.py:251`, `implementation/app.py:36`
- §3.1 — insert — ambiguity — fleet figures must be whole numbers and `dot_number` digits-only — `implementation/routes/reference.py:69`
- §3.1 — insert — ambiguity — `basis_note` required, no status precondition on a determination, and no score/posture/screening recompute — `implementation/routes/reference.py:149`
- §3.1 — insert — ambiguity — driver PATCH fields both optional, always bumps `version`, recomputes no aggregates, and waives only on a supplied `TERMINATED` — `implementation/routes/reference.py:235`
- §3.1 — insert — ambiguity — all three percentile bars capped at 100 and the three constraints evaluated in a fixed order — `implementation/routes/reference.py:348`
- §3.2 — insert — mismatch — validation's attribution gate exempts `REMOVED` driver violations — `implementation/routes/reports.py:191`
- §3.3 — insert — ambiguity — pinning also refreshes the violation's `basic_category` — `implementation/services/cascade.py:130`
- §3.3 — insert — ambiguity — `has_stale_code_pin` is derived at read, never stored, and false for a never-pinned violation — `implementation/routes/helpers.py:27`
- §3.4 — insert — ambiguity — stored severity sums rounded to 1 dp while measures use the unrounded sums; `denominator_value` unrounded — `implementation/services/cascade.py:251`
- §3.6 — insert — ambiguity — evidence may be attached only to an unresolved challenge, else `ERR_INVALID_CHALLENGE_STATE` — `implementation/routes/challenges.py:205`
- §3.6 — revise — mismatch — `review_note` required on every review action, and `ASSIGN` records no officer identifier — `implementation/routes/challenges.py:324`
- §3.6 — insert — ambiguity — `WRONG_CARRIER` cascades against the losing carrier's stamped basis and mints rows only when the report was `SCORED` — `implementation/routes/challenges.py:410`
- §3.6 — revise — mismatch — a `DUPLICATE_REPORT` acceptance is valid from any challengeable status, `AMENDED` included — `implementation/routes/challenges.py:436`
- §3.6 — insert — ambiguity — `INCORRECT_VIOLATION_CODE` re-pins against the report's `severity_basis_utc` and the generated amendment's field shape (`rationale` copies the narrative) — `implementation/routes/challenges.py:455`
- §3.7 — insert — ambiguity — code correction refreshes `basic_category` and re-pins only a previously pinned violation, against the report's stamped basis — `implementation/routes/reports.py:306`
- §3.7 — revise — mismatch — waiver keyed on the violation's `driver_id` no longer matching the assignment; `CARRIER_REATTRIBUTION` waives nothing — `implementation/services/cascade.py:689`
- §3.8 — insert — ambiguity — a `reduced_to_violation_code_id` on a non-`REDUCED` outcome is accepted, must resolve, and is stored inert — `implementation/routes/challenges.py:594`
- §3.8 — revise — mismatch — four preconditions in a fixed order, with `CONVICTED` returning before the violation-active bar — `implementation/routes/challenges.py:620`
- §3.8 — insert — ambiguity — the `REDUCED` push refreshes `basic_category` and re-pins against the report's basis — `implementation/routes/challenges.py:652`
- §3.9 — insert — ambiguity — setting attribution waives other drivers' open assignments; clearing has no state gate and is idempotent — `implementation/routes/reports.py:436`
- §3.9 — insert — ambiguity — `factor_breakdown` entry shape and oldest-first ordering — `implementation/services/cascade.py:631`
- §3.9 — revise — mismatch — starting a session re-checks only `employment_status`, after the status gate — `implementation/routes/plans.py:134`
- §3.9 — revise — mismatch — `VIOLATION_REMOVED`/`ATTRIBUTION_CLEARED` reach only `ASSIGNED`/`IN_PROGRESS`; the other two also reach `OVERDUE` — `implementation/services/cascade.py:20`
- §3.10 — revise — ambiguity — the superseded plan is the most recently created `RETURNED` one — `implementation/routes/plans.py:226`
- §3.10 — insert — ambiguity — items addable only while the plan is `DRAFT`/`RETURNED`/`SUBMITTED`/`IN_REVIEW`, and new items start with empty `rejection_note`/`verified_by_user_id` — `implementation/routes/plans.py:287`
- §3.10 — insert — ambiguity — on `COMMIT` the item-status check precedes the plan-status check; the other three actions are plan-status-free — `implementation/routes/plans.py:327`
- §3.10 — revise — ambiguity — `REJECT` stores the shared optional `note` as `rejection_note` — `implementation/routes/plans.py:350`
- §3.10 — revise — mismatch — branch review checks segregation before branch-already-recorded — `implementation/routes/plans.py:399`
- §3.10 — insert — ambiguity — an `ACCEPT` with no next fitness step leaves the carrier's status and `version` untouched — `implementation/routes/plans.py:441`
- §3.11 — insert — mismatch — sweep 1 re-pins only `ACTIVE`/`RECODED` violations, restamps `severity_basis_utc` only on changed reports, and never touches `scored_at` — `implementation/services/runs.py:53`
- §3.11 — insert — ambiguity — driver aggregates are rebuilt on the same pass, after the scoring sweep — `implementation/services/runs.py:92`
- §3.11 — revise — ambiguity — coaching sweep runs three ordered passes with strict deadline comparisons — `implementation/services/runs.py:126`
- §3.11 — insert — mismatch — `carriers_scored` counts every registered carrier and `scores_updated` is always four times it — `implementation/services/runs.py:76`

Nothing under `implementation/`, `test_suite/` or `test_helpers/` was modified; the only file written is `workspace/PRD_COMPLETED.md`.
