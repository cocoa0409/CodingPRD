# Worklog — task_2345_federal_environmental_review_documentation

## Step 1: Create Task Directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2345_federal_environmental_review_documentation/` and `tasks/task_2345_federal_environmental_review_documentation/workspace/` (directory name was pre-allocated by the caller; no index scan performed).

## Step 2: Generate Scaffold — 2026-09-02T00:03:31.000Z

All three artifacts are complete and the linter passes on the first run.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2345_federal_environmental_review_documentation/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2345_federal_environmental_review_documentation/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2345_federal_environmental_review_documentation/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    66
  §1.1 entities declared:     17
  §1.8 instances scanned:     19
  §1.9 instances scanned:     59
  Calls scanned (§1.8+§1.9):  1396

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files

- `SCAFFOLD.yaml` (2793 lines) — §1.0–§1.7 only, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1294 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (2455 lines) — single key `scaffold_corner_design`

## SCAFFOLD.yaml counts

17 entities, 13 state machines, 2 OCC concurrency rules, 16 calculations, 14 ordered validations, 66 endpoints, 38 errors, 8 roles + SYSTEM, `role_model: segregation_of_duties`, `consistency_model: immediate`, flat `api_prefix: "/"`.

Domain model: ReviewOffice (22 tunable constants) → ProposedAction → ExtraordinaryCircumstanceScreen, PurposeNeedStatement, ScopingPeriod, Issue, Alternative, CumulativeAction, ResourceAnalysis, ConsultationRequest (via Agency), NepaDocument → PublicComment, DecisionDocument → MitigationCommitment / Objection, plus immutable AdminRecordEntry.

## §1.8 difficulty design — 19 instances over all 9 rule_ids

`dual_variant_calc` 2, `combinatorial_formula` 3 (modes a/b/c), `non_linear_state_machine` 2, `transitive_cascade` 2 (one 4-hop), `priority_pair_validation_conflict` 2, `boundary_precision_check` 2, `cross_entity_state_dependency` 2, `resource_temporal_overlap` 2 (half-open scoping intervals vs. closed buffered consultation intervals), `compensating_invariant` 2 (office obligation ledger; unaddressed-issue coverage).

## §1.9 corner design — 9 sections, 77 instances (59 with recipes, 18 `excluded_because` stubs)

entities 11, state_machines 13, calculations 10, validations 10, endpoints 5, errors 16, rbac 5, cross_cutting_complexity_layers 6, consistency_model 1. All 96 instance names unique across both design files; every `difficulty_instance` reference resolves; no stub carries a `test_recipe`.

## Design adjudications made while generating

- **ScopingPeriod creation precondition relaxed** to `review_stage IN {CLASSIFIED, SCOPING}`; a second period on one action leaves the stage unchanged. Without this, `ERR_SCOPING_PERIOD_OVERLAP` and the first `resource_temporal_overlap` instance were unreachable.
- **SCOPING→ANALYSIS advance moved from a precondition into a conditional side effect**: the stage advances only once *every* ScopingPeriod is CLOSED, but closing one of several open periods succeeds and simply does not advance. This removed an ambiguity (reject vs. no-advance) for the multi-period corner case.
- **Specific-error refinements pinned in asserts** where a generic priority check would otherwise apply: `ERR_MITIGATED_FONSI_WITHOUT_COMMITMENT` refines the priority-8 state check, and `ERR_UNADDRESSED_ISSUES` refines priority 10 when consultations are complete but issue coverage is missing.
- **All numeric literals pre-computed and re-verified against the final formulas** (cumulative 60.04, unmitigated 70.21 / mitigated 58.21, feasibility 35.00 / 76.75 / 16.25, completeness 33.33 → 50.00, lifecycle 2597250, cap breach 890000000 + 17800000 = 907800000 > 900000000).
- **OCC versions are always captured, never literal**; the `corner_action_version_advances_on_each_declared_action_write` instance documents that only adjudicate/classify/adopt advance `ProposedAction.version`, which is what makes the pre-scoping capture still valid at adopt.

## Step 3: Copy Shared Files — 2026-09-02T00:03:31.000Z

Copied `INSTRUCTION.md` → `tasks/task_2345_federal_environmental_review_documentation/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T00:17:50.000Z

PRD written to `workspace/PRD.md` — 404 lines, ~11,280 words. Ends at §5; no audit footer in the file.

## Structure

**§1 Introduction** — 3 paragraphs framing the NEPA review office, the defensibility problem, and the two audiences (review staff needing computed arithmetic, officials needing enforced separation of duties and statutory clocks).

**§2 Global Specifications** — 12 subsections: 2.1 RBAC (8 roles, `X-User-ID`/`X-User-Role`, opaque vs. `AgencyLiaison` agency-backed identity); 2.2 API Response Structure (pasted verbatim from the skill fragment); 2.3 Pagination and List Filters; 2.4 Common Resource Properties and the Administrative Record (`AdminRecordEntry` as the sole entity with no `updated_at`/`version`, `sequence_no` gap-free 1-based numbering, cascade append order); 2.5 Rejection Precedence (bands 1–14, plus the dedicated-code-beats-family-code rule); 2.6 Path Resolution and Referential Coherence; 2.7 Logical Clock, Intervals and Whole-Day Arithmetic (startup default `2026-08-01T00:00:00Z`, half-open scoping vs. closed buffered consultation intervals); 2.8 Numeric Precision and Pinned Evaluation Order; 2.9 Optimistic Concurrency Control; 2.10 Office Policy Parameters (all 20, with defaults and constraints); 2.11 Segregation of Duties; 2.12 The Office Obligation Ledger (closed form + compensating sign/vacate pair).

**§3 Business Logic** — 9 subsections: office and agency setup; intake and extraordinary-circumstance screening (incl. the `SUBMITTED → RETURNED → SUBMITTED` rework cycle); classification and the 3-hop escalation cascade; purpose and need plus alternatives range; scoping periods and issues; interagency consultation and agency capacity; cumulative baseline and resource-effects analysis (both score variants, finalize/reopen as an exact compensating pair); publication, comment period, response to comments (independent `publication_status` × `comment_status` axes); decision, mitigation obligations, objection/remand, record certification.

**§4** 66-endpoint table (Method / Path / Description / Authorized Roles). **§5** 38-error table.

## Audit results

```
Field coverage check:
- entities[].fields: 179 required, 179 present, 0 missing
- endpoints[].request_body: 95 required, 95 present, 0 missing
- endpoints[].query_params: 24 required, 24 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 14 checked, 14 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 42 checked, 42 fully expressed, 0 missing
- calculations[]: 16 checked, 16 fully expressed, 0 missing
- validations[] conditions: 38 checked, 38 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 107 checked, 107 expressed, 0 missing
- entities[].fields[] structured content: 179 checked, 179 reconstructible from prose, 0 missing
- sibling-branch symmetry: 11 groups checked, 11 with equal prose density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 873
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Two ambiguities in the scaffold required a determinate ruling, both stated explicitly in the PRD: (1) where a priority band bundles several conditions under a family code but the catalogue also carries dedicated codes (e.g. `ERR_UNADDRESSED_ISSUES` inside band 10, `ERR_INSUFFICIENT_ALTERNATIVES` inside band 12), the dedicated code wins and the family code retains only the conditions with no dedicated code — §2.5 spells out which conditions land where; (2) office minima for screened-in alternatives and comment-period length are defined only for EA and EIS, so a `CE_MEMORANDUM` is stated to be bound by neither.

The two withheld design files were never opened, and no sibling task directory was accessed.

## Step 5: Generate Unit Tests — 2026-09-02T01:45:00.000Z

Generation complete. Both remaining suite files are written and every audit is clean.

## Files created

**`test_helpers/` (9 modules, Stage 1)** — `__init__.py` (single-import barrel), `api_client.py`, `api_errors.py` (`ApiErrorId` + `HTTP_STATUS_CODES`), `assertions.py`, `constants.py`, `factories.py`, `fixtures.py` (tiered chain builders + canonical data), `test_users.py`, `types.py`.

**`test_suite/` (conftest + 9 modules, Stage 2)** — 96 tests total:

| file | tests | queue A | queue B |
|---|---|---|---|
| test_01_office_agency_and_action_intake | 16 | 0 | 16 |
| test_02_extraordinary_circumstance_screening | 6 | 4 | 2 |
| test_03_purpose_need_and_alternatives | 5 | 0 | 5 |
| test_04_scoping_periods_and_issues | 8 | 6 | 2 |
| test_05_interagency_consultation | 6 | 2 | 4 |
| test_06_cumulative_baseline_and_significance | 12 | 6 | 6 |
| test_07_document_publication_and_comments | 17 | 8 | 9 |
| test_08_decision_obligations_and_signature | 16 | 8 | 8 |
| test_09_objections_remand_and_record_certification | 10 | 4 | 6 |
| **total** | **96** | **38** | **58** |

## Coverage audit

- Queue A: all 19 §1.8 instances translated, exactly 2 tests each (38) — no under-covered instance.
- Queue B: 59 non-stub §1.9 instances, 58 translated at ≥1 test each; none of the 18 `excluded_because:` stubs was translated.
- Tag audit: every test carries exactly one `Design:` line, it is the last line of the docstring, and every tag resolves to a real instance under the correct `rule_id` / `section`. One mis-sectioned tag found and fixed (`corner_publish_with_every_condition_satisfied_succeeds` was tagged `Corner/endpoints/…`; it lives in `validations`).
- PRD-citation audit: 0 mismatches — every quoted citation survives a literal whitespace-normalised grep of `workspace/PRD.md` (8 fabricated quotes in test_07 were caught and replaced earlier; 2 sub-8-word quotes in test_09 were replaced with full rule-bearing sentences).
- `pyflakes test_suite/*.py` clean; all modules compile. No `pytest.mark.skip`/`xfail` anywhere.

## Instances skipped (1)

`corner_action_version_advances_on_each_declared_action_write` (`cross_cutting_complexity_layers`) — its asserted `version == 3` / `version == 4` are the claim, and they contradict PRD §2.4 + §3.5, under which opening the first scoping period also advances the action (stage move). The PRD does not uniquely derive the design's numbers, so the instance was dropped rather than weakened.

## Design-vs-PRD conflicts resolved in the PRD's favour (asserted the PRD value, not the design's)

- DRAFT decision `binding_obligation_cents` / `credit_points` / `mitigated_max_score`: design says `null`; PRD §3.9 says `0` / `0.0` — asserted the PRD values (test_08 `TestSignatureEffectsAndReads`, `TestSignatureBandOrder`).
- Unpublished document `comment_period_days`: design `null`, PRD `0`.
- `office_obligation_ledger_restored_exactly_after_sign_then_remand`: the design's absolute `record_entry_count` 8→9→12 is chain-specific, so the conserved-quantity claim is asserted as exact deltas (+1 on signature, +4 across sign/file/resolve/vacate) plus gap-free `sequence_no`, with the ledger literals (0 → 3487823 → 0) intact.

Key arithmetic pinned in the new files: per-commitment lifecycles 1213973 / 2107763, `base` 3321736 (≠ 3321735), `credit_points` 13.29 (≠ 13.95), fee 166087 (≠ 174391), `binding` 3487823, committed 3300000, divergence 187823, `mitigated_max_score` 56.92, twin-stream base 2427946 (≠ 2427945), cap-breach 890000000 → fee 17800000 → 907800000, single-commitment base 2597250, objection window 2026-11-01T12:00:00Z → 2026-12-16T12:00:00Z (exclusive).

*Orchestrator note: Steps 5 and 6 were launched in separate messages rather than concurrently. To preserve the physical isolation the skill's concurrency requirement provides, the Step 6 prompt carried an absolute prohibition on reading `test_suite/`, `test_helpers/`, and both design YAMLs; the Step 6 subagent confirmed it read only INSTRUCTION.md, SCAFFOLD.yaml, and PRD.md.*

## Step 6: Generate Implementation — 2026-09-02T02:17:36.000Z

Implementation complete and verified.

## Files created (23, all under `workspace/implementation/`)

Boot/config: `start.sh` (executable), `requirements.txt` (`Flask>=2.2`), `app.py`
Infrastructure: `db.py`, `errors.py`, `response.py`, `middleware.py`, `validation.py`
Services: `services/calc.py`, `services/record.py`, `services/rollups.py`, `services/cascade.py`, `services/__init__.py`
Routes: `routes/config.py`, `routes/actions.py`, `routes/scoping.py`, `routes/alternatives.py`, `routes/analysis.py`, `routes/consultations.py`, `routes/documents.py`, `routes/decisions.py`, `routes/helpers.py`, `routes/__init__.py`

## Endpoint count: 66

Programmatically diffed the Flask URL map against the PRD §4 table: **66 PRD rows, 66 implemented, zero missing, zero extra** (`static_folder=None` so Flask adds no `/static` route).

## Notable design decisions

- **Storage**: `db.py` holds 17 plain dicts, created empty at import. No seeding, no persistence, no I/O. Insertion order preserved via a monotonic `_seq` used for list ordering.
- **Two clocks**: `created_at`/`updated_at` use real wall time (stable ordering); every *logical* instant (`occurred_at`, `signed_at`, `responded_at`, `comment_period_start_at`, `record_certified_at`, `statutory_due_at`, objection window bounds) uses the settable logical clock. Input-supplied datetimes are echoed verbatim; computed ones are canonical ISO with milliseconds + `Z`.
- **Version bumping**: exactly +1 per row per request, enforced by a per-request `g.touched_rows` set, so multi-hop cascades that touch a row twice still bump it once.
- **Rounding**: `decimal.Decimal` + `ROUND_HALF_UP` throughout; the three pinned orders (per-entry cumulative rounding, per-commitment monitoring escalation, single forward pass for decision fiscals with frozen `credit_points`) are implemented literally in `services/calc.py`.
- **Compute-then-commit on sign**: fiscals and the office-ceiling test run before any mutation, so an `ERR_OBLIGATION_CAP_EXCEEDED` signature leaves zero partial state (verified).
- **Cascades** in `services/cascade.py`: EC escalation (CE→EA, stage rewind, CE memo supersession) and decision vacatur (commitments RELEASED, exactly-compensating office ledger reversal, FINAL→DRAFT documents, stage rewind). Record entries are appended direct-effect-first, then cascade, with SYSTEM actor/null `actor_user_id`.
- **Interval conventions** kept distinct: scoping is half-open per `scoping_kind` (adjacency allowed); consultation capacity is a closed interval with aggregate counting (a shared endpoint collides).
- **Precedence**: `ERR_TEMPORAL_CONFLICT` reserved solely for premature record certification (PRD §2.5 band 13), so `end_at <= start_at` is `ERR_INVALID_REQUEST`. Dedicated state codes (`ERR_ALTERNATIVE_STALE`, `ERR_NO_ADOPTED_PURPOSE_NEED`, `ERR_ANALYSIS_LOCKED`, `ERR_RECORD_ALREADY_CERTIFIED`, `ERR_EC_SCREEN_NOT_TRIGGERED`) are band-8 and precede band 11–13 codes. Error catalogue transcribed 1:1 from PRD §5 (38 entries, statuses verified against the table).

## Boot + behaviour confirmation

Server boots cleanly from a fresh process (`PORT=… bash start.sh`), and a brand-new process serves an empty store (`GET /proposed-actions` → `[]`, `total_count: 0`). Three smoke suites, all passing:

1. **Full happy path** (office → agency → action → EC screen → adjudicate → classify → PN draft/adopt → alternatives → scoping open/close → issues → cumulative actions → analysis finalize → consultation concur → publish → comment → close → respond → finalize → decision draft → mitigation → sign → objection file → remand → record entries). Hand-computed arithmetic matched exactly: cumulative 60.00, unmitigated 69.00, mitigated 63.00, lifecycle 2 552 500 cents, credit 6.00, fee 89 338, binding 2 641 838, and the vacatur restored the office ledger to 0.
2. **Cascades + precedence**: escalation superseded the CE memo with record entries `EC_SCREEN_ADJUDICATED → CLASSIFICATION_ESCALATED (SYSTEM) → DOCUMENT_SUPERSEDED (SYSTEM)`, gap-free 1-based sequence; PN supersession marked the pinned alternative STALE; scoping overlap rejected while adjacency and a different `scoping_kind` were accepted; certify-record blocked early (`ERR_TEMPORAL_CONFLICT`), then by a pending objection, then succeeded and was idempotency-guarded.
3. **Guard rails**: office cross-field checks, agency suspension/capacity/scope, cross-role consultation outcome misuse (403), scoping-too-short, duplicate resource analysis, `ERR_MITIGATION_BASIS_REQUIRED`, `ERR_ANALYSIS_LOCKED`, `ERR_MITIGATED_FONSI_WITHOUT_COMMITMENT`, both optimistic-concurrency 412s, and the obligation cap leaving no partial state.

All smoke-test servers have been stopped and `__pycache__` removed. Only `workspace/implementation/` is new in git status; no benchmark files were read or modified.

## Step 7: Run Tests and Iterate — 2026-09-02T05:25:23.000Z

## Summary

### Iterations run
8 full 8-round parallel sweeps (64 harness rounds total), plus one serial per-test verification run of all 96 tests against a fresh server per test.

- **Sweep 1 (pre-fix, scouting):** 3 distinct `FAILED` tests, all in `test_07`.
- **Sweeps 2–9 (post-fix, 56 rounds):** `failed == 0` in **every single round**. Individual rounds reached a clean **96/96** (sweep 5 round 3; sweep 6 rounds 1 and 3). In the final sweep every one of the 96 tests passed in at least one round.

### Tests deleted
**None.** No test failed STEP 1a (coverage) or STEP 1b (unique derivability) — all three real failures were test-side precondition bugs, not PRD-silence collapses.

### Fixes applied to `test_helpers/`
- `test_helpers/fixtures.py` — `setup_analysis_stage_action()`: added the `with_analysis` / `finalize_analysis_flag` / `analysis_overrides` parameters (opening and finalising the canonical biological analysis when asked). The published option bundle `NO_ISSUE_NO_BASELINE_NO_ANALYSIS` carries `with_analysis: False`, but only `setup_publish_ready_action` accepted that key, so the bundle fell through `**opts` down the chain and died with `TypeError: setup_screened_action() got an unexpected keyword argument 'with_analysis'` — a pure setup crash, before any request was issued. Fixed 2 tests (`test_publication_succeeds_when_every_gate_is_satisfied`, `test_the_publish_response_already_carries_the_derived_fields`).

### Fixes applied to `test_suite/`
- `test_suite/test_07_document_publication_and_comments.py:86` — `test_publish_moves_both_axes_and_closing_comments_moves_only_one` built its precondition with `_draft_document_at_analysis(with_baseline=True)`, which records a `SIGNIFICANT` BIOLOGICAL scoping issue and a cumulative baseline but **no finalized analysis**. The PRD-faithful implementation correctly answered `409 ERR_UNADDRESSED_ISSUES` ("every significant scoping issue must have a finalized analysis behind it"), so the positive-control publish never happened. Changed the setup call to `with_baseline=True, with_analysis=True`. The implementation's PRD-required gate was left untouched; only the fixture's precondition was corrected.

### Fixes applied to `implementation/`
- **No logic changes.** The only edits are the boot-cost change made before the failures were known: `workspace/implementation/start.sh` reduced to `exec python3 app.py`, with the dependency bootstrap moved into a `try/except ModuleNotFoundError` at the top of `workspace/implementation/app.py`. This removed a separate `python3 -c "import flask"` probe that cost ~3.4 s on every per-test reboot. No endpoint, field, side effect, or seeded data was added; storage remains in-memory only.

### Residual non-passes are harness infrastructure, not the artifact
The exit condition "all 8 rounds `passed == total`" was not reached, and the blocker is outside the task directory. Every non-pass in all 56 post-fix rounds is a **setup-hook crash in the runner**, verbatim:

```
failed on setup with "subprocess.TimeoutExpired: Command 'pids=$(lsof -ti:<port> -sTCP:LISTEN 2>/dev/null); ...' timed out after 5 seconds"
```

That is `_kill_port()` in `prd-bench-local-runner/src/prd_bench_local_runner/pytest_plugin.py`, which calls `lsof` with a hard `timeout=5`. The host is running ~20 sibling task pipelines' sweeps concurrently (load average 120–255 on 32 cores, ~3,300 processes, ~10,000 open fds, 174 holders in the port registry); measured directly, `lsof -ti:<port> -sTCP:LISTEN` takes **1.5–6.3 s** there, so it intermittently blows the 5 s budget. Error counts tracked host load exactly (208 errors at load 255 → 15 at load 120) while `failed` stayed at 0 throughout.

Independent confirmation that the suite itself is green: a serial run of all 96 tests, each against its own freshly booted server (same isolation semantics, no `lsof`), produced zero genuine failures — the only two aborts were `Connection refused` while two of my own verification loops were competing for the box, and they passed on retry.

### Orchestrator verification of the above

Independently confirmed by the orchestrator against the on-disk `results.{1..8}.json` from the final sweep plus one fresh single round:

- Final sweep, 8 rounds: `failed == 0` in all 8 (`passed` 89–94 of 96); union analysis shows **all 96 distinct tests passed in ≥1 round, 0 tests never-passing**; every one of the 31 non-passes carries status `error`, not `failed`.
- Fresh single round run by the orchestrator at 2026-09-02T05:25Z (host load 129): `passed 93, failed 0, total 96`; all 3 non-passes are the identical `subprocess.TimeoutExpired ... lsof -ti:47733 -sTCP:LISTEN ... timed out after 5 seconds` setup-hook crash in the runner's `_kill_port()`, i.e. harness infrastructure under host contention, not the task artifact.

## Step 8: Finalize PRD — 2026-09-02T05:28:20.000Z

`workspace/PRD_FINALIZED.md` is on disk as a **verbatim copy** of `workspace/PRD.md` — the minimal patch is **zero edits**.

## Line counts
- `workspace/PRD.md` — 403 lines
- `workspace/PRD_FINALIZED.md` — 403 lines
- Delta: 0 lines, 0.0% (`diff -q` reports the files identical)

## Changes
None. Every `<step_7_diff>` item traced to behavior the PRD already determines uniquely, or to non-behavioral plumbing.

## Per-item pre-edit search log (all three concluded "no edit")

**Item 1 — `test_helpers/fixtures.py` `setup_analysis_stage_action()` gained `with_analysis` / `finalize_analysis_flag` / `analysis_overrides`.**
- (a) Subject: the publication gate stack exercised by the positive-control tests, and whether a *finalized analysis must exist* to publish.
- (b) Enumerated/read: `workspace/implementation/routes/documents.py:94-170` (`publish_document`: all five gates, in impl order `publication_status` → `review_stage` → `unaddressed_issue_count` → required consultations → `document_type`/classification → alternatives minimum → comment-length minimum, with the `CE_MEMORANDUM` bypass), `routes/documents.py:177-187` (`close_comment_period`), `services/calc.py` (`required_consultation_types`), `db.floor_days`/`logical_now`; plus the assertions the two revived tests make — `assert_document` in `test_helpers/assertions.py:216`, `comment_period_days`, `response_completeness_pct`, `record_entry_count`.
- (c) No wording adjustment needed. PRD §3.8 L253/L255 already pin the whole gate stack and its dedicated-code order (reinforced by §2.4 L111 band-10 ordering), L125 pins `comment_period_days` as floored elapsed days, L259 pins `response_completeness_pct == 100.00` at zero substantive comments, and L179/L217 pin the counters. Crucially the impl imposes **no** `finalized_analysis_count > 0` precondition on publish, matching the PRD's silence on one — so the `with_analysis: False` bundle passing is PRD-derivable, not an impl-only choice. Pure helper-signature (`TypeError`) bug; nothing to pin.

**Item 2 — `test_suite/test_07_document_publication_and_comments.py:86` precondition changed to `with_baseline=True, with_analysis=True`.**
- (a) Subject: the `ERR_UNADDRESSED_ISSUES` publish gate and the definition of `unaddressed_issue_count`.
- (b) Enumerated/read: `routes/documents.py:108-112` (the gate itself), `errors.py:40` (409 mapping), every writer of `unaddressed_issue_count` — issue recording in `routes/scoping.py`, analysis finalize/reopen in `routes/analysis.py`, and the rollup helper in `services/rollups.py` — plus `test_helpers/fixtures.py:204` (`record_issue` default payload yields a `SIGNIFICANT`/`OPEN` biological issue).
- (c) No wording adjustment needed. PRD §3.8 L253 states verbatim that "the action's `unaddressed_issue_count` must be exactly zero, or the request is rejected with `ERR_UNADDRESSED_ISSUES`", and §3.5 L217 defines the counter as significant + `OPEN` + no `FINAL` analysis on the same `resource_area`. The impl's 409 was the PRD-mandated answer; the fixture simply built an unpublishable action. Test-side bug only.

**Item 3 — `implementation/start.sh` reduced to `exec python3 app.py`, dependency bootstrap moved into a `try/except ModuleNotFoundError` in `app.py`.**
- (a) Subject: process startup / dependency bootstrap.
- (b) Enumerated/read: `workspace/implementation/start.sh` (full file), `workspace/implementation/app.py:1-25` (the guarded `pip install` fallback), and grepped `workspace/PRD.md` + `workspace/INSTRUCTION.md` for `start.sh` / `pip install` / port / bootstrap — every hit is in `INSTRUCTION.md` (lines 9-40); `PRD.md` contains none.
- (c) No wording adjustment needed. Startup mechanics are governed by `INSTRUCTION.md`, not the PRD; no endpoint, field, side effect, or seeded data changed, and storage remains in-memory-only exactly as `app.py`'s docstring and the PRD assume.

## Step 9: Complete PRD — 2026-09-02T05:40:29.000Z

All pins applied. `PRD_COMPLETED.md` exists on disk at `workspace/PRD_COMPLETED.md`.

## Counts

- `workspace/PRD_FINALIZED.md`: 403 lines, 84,391 bytes / 84,610 chars
- `workspace/PRD_COMPLETED.md`: 403 lines, 91,749 bytes / 91,991 chars
- Char delta: **+7,358 bytes (+7,381 chars)**; line count unchanged (every change is an in-paragraph insert or revision; no new sections, no new paragraphs)
- Changes: **38 total — 33 ambiguity-pins, 5 mismatch-revisions**, touching 30 distinct paragraph lines

## Changes

- §2.1 — revise — ambiguity — blank `X-User-ID`/`X-User-Role` treated as absent → `ERR_UNAUTHENTICATED` — `middleware.py:25`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + 20 random uppercase alphanumerics — `response.py:14`
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from real wall-clock, not the logical clock — `response.py:20`
- §2.3 — insert — ambiguity — non-integer / out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` — `validation.py:244,262`
- §2.3 — revise — **mismatch** — per-collection filter lists corrected to the sets actually accepted (screens by `status`; PN by `status`; periods by `scoping_kind`+`status`; consultations by `action_id`/`agency_id`/`status`/`consultation_type`; documents by `document_type`/`publication_status`/`comment_status`; decisions by `action_id`/`selected_alternative_id`/`status`/`decision_type`; mitigations by `decision_id`/`source_analysis_id`/`monitoring_status`/`status`) — `routes/decisions.py:125,175`, `routes/documents.py:86,275`, `routes/consultations.py:90`, `routes/scoping.py:262`
- §2.3 — insert — ambiguity — unrecognised query parameters ignored, not rejected; filters compare the string form of the stored value — `validation.py:278-281`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` from real wall-clock; `version` advances exactly once per request per row regardless of how many fields are touched — `db.py:93,103-110`
- §2.4 — insert — ambiguity — exactly three entry codes carry `actor_role` `SYSTEM`, plus the full `entry_code` → `related_entity_type`/ref pairing table — `services/record.py:9,17,25`
- §2.5 — insert — ambiguity — a no-body endpoint treats any supplied field as an unknown field; non-object or unparseable JSON fails identically — `validation.py:57`
- §2.9 — insert — ambiguity — `expected_*_version` that is not a non-negative integer fails as `ERR_INVALID_REQUEST` — `validation.py:88`, `routes/decisions.py:37`
- §2.7 — insert — ambiguity — setting the clock is the one write returning no resource: `200 OK` with empty `data` — `routes/config.py:179-182`
- §3.3 — insert — ambiguity — finding-`code` membership test runs after path resolution but before `review_stage`, fails `ERR_INVALID_REQUEST`; duplicate codes allowed, `triggered_codes` still deduplicated — `routes/actions.py:107,121`
- §3.3 — insert — ambiguity — multiple screens per action allowed with no guard on prior screens' status; count unbounded — `routes/actions.py:121`
- §3.3 — revise — **mismatch** — `adjudicator_note` is a required field on every disposition; only `RETURNED` additionally requires it non-empty — `routes/actions.py:160-166`
- §3.3 — revise — ambiguity — `ERR_EC_SCREEN_NOT_TRIGGERED` evaluated only after `status == SUBMITTED` is confirmed — `routes/actions.py:175-180`
- §3.3 — insert — ambiguity — record-entry ordering within the cascade: `EC_SCREEN_ADJUDICATED`, then `CLASSIFICATION_ESCALATED`, then one `DOCUMENT_SUPERSEDED` per document in `created_at` order — `routes/actions.py:200-206`, `services/cascade.py:42`
- §3.3 — revise — ambiguity — resubmission applies the code-membership test before the `RETURNED` status check — `routes/actions.py:216-218`
- §3.3 — insert — ambiguity — resubmission neither reads nor moves `review_stage` and appends no record entry — `routes/actions.py:211-227`
- §3.3 — revise — **mismatch** — escalation keys on a `TRIGGERED` disposition setting the flag true, not on a false→true transition — `services/cascade.py:14`, `routes/actions.py:203-206`
- §3.3 — insert — ambiguity — an action with null `classification` escalates nothing and keeps its stage — `services/cascade.py:14`
- §3.4 — insert — ambiguity — `ERR_NO_ADOPTED_PURPOSE_NEED` precedes the `goal_alignment_codes` membership test — `routes/alternatives.py:38`
- §3.4 — revise — ambiguity — duplicate-`label` `ERR_CONSTRAINT_VIOLATION` tested after both prior checks; creation is stage-free — `routes/alternatives.py:51`
- §3.5 — insert — ambiguity — the OPEN period is the only gate on recording an issue; no `review_stage` constraint or movement — `routes/scoping.py:237-240`
- §3.6 — revise — ambiguity — `ERR_AGENCY_SUSPENDED` precedes the capacity test; consultation creation is stage-free — `routes/consultations.py:40,55`
- §3.6 — insert — ambiguity — role/outcome pairing `ERR_ROLE_NOT_PERMITTED` evaluated after path resolution and before both agency-scope and state checks — `routes/consultations.py:116-127`
- §3.6 — revise — ambiguity — `conditions_text` supplied with a non-conditional outcome is accepted and ignored, field stays null — `routes/consultations.py:144-145`
- §3.7 — insert — ambiguity — baseline entries and analyses are admissible at any stage and move none — `routes/analysis.py:82`
- §3.7 — insert — ambiguity — reopening leaves `cumulative_effect_score`, `unmitigated_score`, `mitigated_score` at their stored values (only the three determination fields are nulled) — `routes/analysis.py:195`
- §3.8 — revise — ambiguity — document creation initialises the four comment rollups (0/0/0, 100.00) and is stage-free; type match is its only coherence gate — `routes/documents.py:62-78`
- §3.8 — revise — **mismatch** — publish evaluates the `document_type`-vs-`classification` re-match at band 11, after the unaddressed-issues and required-consultation checks, not alongside the state checks — `routes/documents.py:105-133`
- §3.8 — insert — ambiguity — a `CE_MEMORANDUM`'s `comment_period_end_at` may sit at or before now, yielding `comment_period_days` ≤ 0 — `routes/documents.py:136-161`
- §3.8 — revise — **mismatch** — `COMMENT_PERIOD_CLOSED` is appended unconditionally, not only when the stage advances — `routes/documents.py:192-201`
- §3.9 — insert — ambiguity — `ERR_ALTERNATIVE_STALE` precedes all mismatch tests, whose order is decision-type/classification, then same-action, then `SCREENED_IN`; drafting is stage-free — `routes/decisions.py:83-90`
- §3.9 — revise — ambiguity — signature is all-or-nothing: the becoming-binding set is computed and read by every check, rows are written only once the whole signature passes; any rejection (including the ceiling) leaves commitments `PROPOSED`, decision `DRAFT`, ledger untouched — `routes/decisions.py:207-244`
- §3.9 — revise — ambiguity — capacity-derived reduction points are unbounded (never the minimum) when `cost_per_reduction_point_cents` is zero — `services/calc.py:214`
- §3.9 — insert — ambiguity — objection filing checks `SIGNED` before standing and window; `AgencyLiaison` filing carries no agency-scope check — `routes/decisions.py:300-312`
- §3.9 — revise — ambiguity — the already-certified test runs first on certification, preferred over the `ERR_INVALID_STATE` the terminal stage would raise — `routes/decisions.py:264-267`
- §4 — insert — ambiguity — mutating operations return the path row, except classify and certify-record which both return the updated `ProposedAction` — `routes/actions.py:82`, `routes/decisions.py:288`
