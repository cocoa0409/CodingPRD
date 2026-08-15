# Worklog — task_1605_liquidity_stress_testing_contingency

## Step 1: Create Task Directory — 2026-08-14T01:06:00.000Z

Task directory `tasks/task_1605_liquidity_stress_testing_contingency/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per invocation instructions; no index scan performed, no other task_* directory touched.

## Step 2: Scaffold Generation — 2026-08-14T02:01:00.000Z

Scaffold generation for task_1605 complete. All three artifacts are written and pass lint cleanly.

### Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1605_liquidity_stress_testing_contingency/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys): 14 entities, 60 endpoints, 26 error codes, 9 state machines, 8 calculation rules, 25 ordered validations, 5 roles, 2 OCC concurrency rules
- `/home/ubuntu/github/CodingPRD/tasks/task_1605_liquidity_stress_testing_contingency/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`: 9 rules × 19 instances (dual_variant_calc, combinatorial_formula ×3 modes a/b/c, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant ×2 each)
- `/home/ubuntu/github/CodingPRD/tasks/task_1605_liquidity_stress_testing_contingency/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`: 43 instances (39 active + 4 `excluded_because` stubs) across all nine claim-extraction-guide sections

### Key design decisions

- **Complexity profile**: `compliance_audit` (primary) + `ledger_reconciliation` (secondary); layers: cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, optimistic_concurrency; flat topology; segregation_of_duties role model (playbook creator ≠ approver, breach acknowledger ≠ remediator).
- **Dual-variant heart**: CONTRACTUAL vs BEHAVIORAL cash-flow projections (600,000,000 vs 400,000,000 outflows on identical inputs, hand-computed and pinned) and BASELINE vs STRESS HQLA haircuts (2,000,002 vs 1,800,002 with a per-asset-floor rounding trap that differs from sum-then-floor by exactly 1 cent).
- **Posture engine**: EWI readings → amber/red bands → append-only PostureSnapshot (auto-escalation on RED, committee-gated one-step de-escalation hysteresis) gates playbook activation; entering SEVERE/CRISIS auto-escalates OPEN breaches.
- **Two true-race OCC rules**: PATCH playbook (`expected_playbook_version`) and create-projection-run-with-supersede (`expected_scenario_version`), both 412/ERR_STALE_VERSION.
- **Two transitive cascades**: pledge release → line recompute → auto-suspension → action BLOCKED; RED reading → band → posture snapshot → breach auto-escalation.
- One design correction made mid-build: prerequisite enforcement moved entirely to execute-time (`ERR_PREREQUISITE_ACTION_INCOMPLETE`), since activation-time readiness gating made that error unreachable.

### Verification (verdict block, verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(60 endpoints, 14 entities, 19 §1.8 instances, 43 §1.9 instances, 419 calls scanned)

Auxiliary checks also pass: placeholder closure clean (every `${var}` bound by an earlier `captures:`), no forbidden concurrency vocabulary, all `grounds:` resolve into §1.1–§1.7, all 26 error ids and all 60 endpoints exercised by at least one instance, and instance names are unique across both design files. Worklog updated.

## Step 3: Copy Shared Files — 2026-08-14T02:02:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1605_liquidity_stress_testing_contingency/workspace/INSTRUCTION.md` (bash, no subagent).

## Step 4: PRD Generation — 2026-08-14T02:22:00.000Z

All three hard contracts pass after the repair pass. Final summary:

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_1605_liquidity_stress_testing_contingency/workspace/PRD.md` — a PRD for the Liquidity Stress Testing & Contingency Funding Plan API, projected from `SCAFFOLD.yaml` (the two test-targeting index files were not opened, per the constraint).

**Document skeleton (domain-derived, not templated):**
- §1: 2-paragraph introduction from business context + system scope.
- §2: 10 subsections — RBAC with per-role opaque-identity prose; verbatim §2.2 response envelope (byte-identical to the canonical source, confirmed mechanically); pagination (limit 10/1/100, offset 0, `created_at` ascending with the `snapshot_seq` exception); the logical clock (fixed epoch 2026-08-01T00:00:00Z, `to_iso8601`/`current_utc`); resource identity/versioning incl. the three append-only event entities lacking `updated_at`/`version`; cents/bps/pct conventions with pinned floor-per-item rounding; OCC rules naming both guarded endpoints with `ERR_STALE_VERSION` (412); left-to-right reference resolution; the full 10-tier validation order with every error ID placed in its tier; atomicity of cascades.
- §3: 9 subsections organized by treasury workflow (scenarios → projections → HQLA → lines/collateral → funding concentration → EWI/posture → limits/breaches/intraday → playbook construction/capacity test → approval/activation/execution/closure). All 8 calculations rendered as reconstructible prose (per-asset-floor-then-sum HQLA with BASELINE/STRESS variants, CONTRACTUAL vs BEHAVIORAL projection, funding concentration with lexicographic tie-break, four-ordinal posture machine with hysteresis, 3-step borrowing power, capacity test with per-line aggregate, intraday chronological guard, strict-boundary breach detection with dedupe). All state machines, SoD rules, cascades (release → recompute → suspension → blocking; RED → READING_AUTO snapshot → OPEN→ESCALATED escalation), and validation `applies_to` scopes are expressed.
- §4: 60-row endpoint table (Method/Path/Description/Roles only). §5: 26-row error catalogue (ID/status only).

**Hard Contract Reports:**
```
Field coverage check:
- entities[].fields + endpoint inputs/outputs/query params: 106 required, 106 present, 0 missing (two-pass; pass 1 caught limit_id, metric_id — repaired in §3.6/§3.7)
Status: PASS

Rule coverage check:
- validation priority ordering: expressed as explicit 10-tier ordered prose in §2.9
- concurrency_rules OCC rejections: 2/2 expressed (endpoint + expected_<parent>_version + ERR_STALE_VERSION/412)
- state machine transitions: all expressed with preconditions and side effects (incl. system transitions: DRAFT supersede/discard, FINALIZED→SUPERSEDED, encumbrance cycling, ACTIVATED→EXECUTING, BLOCKED fan-out, OPEN→ESCALATED auto-escalation)
- calculations: 8/8 fully expressed in precise prose, constants embedded, no pseudocode (mechanical scan: no ==/>=/<=/!= leaks, no fuzzy words)
- validations: all 25 rules matchable to error IDs in §2/§3 prose; all 26 error IDs present in prose
- endpoint side effects / applies_to scopes: all expressed
- sibling-branch symmetry: CONTRACTUAL/BEHAVIORAL, BASELINE/STRESS, ASSET_SALE/LINE_DRAWDOWN, ACKNOWLEDGED-vs-ESCALATED remediation branches all at equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 493
- tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path combos: 0
Status: PASS
```

## Step 5: Unit Test Generation — 2026-08-14T02:42:00.000Z

All audits pass. The generation is complete.

### Report

Generated complete test infrastructure for task_1605 (Liquidity Stress Testing & Contingency Funding Plan).

**`test_helpers/`** (9 files):
- `types.py` — all 14 entities as TypedDicts + 19 status/enum vocabularies; append-only event entities (MetricReading, PostureSnapshot, IntradaySnapshot) correctly omit `updated_at`/`version` per PRD §2.5.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per all 43 PRD §4 endpoints.
- `api_errors.py` — all 26 error IDs with PRD §5 HTTP statuses, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions plus `assert_borrowing_power_invariants` (PRD §3.4 pinned order) and `assert_net_position_invariant` (§3.7).
- `factories.py`, `constants.py` (haircut bps 0/1500/2500, posture ordinals, clock anchor 2026-08-01T00:00:00Z), `test_users.py` (opaque roles; named SoD anchors `ta_1`/`ro_1`/`ro_2`/etc.).
- `fixtures.py` — composite builders: `setup_line_with_pledge`, `make_tested_playbook` / `make_approved_playbook` / `make_activated_playbook` (SoD-threaded creator/approver), `setup_active_drawdown_playbook`, `setup_executing_drawdown`, `setup_red_metric_with_limit`, `setup_wholesale_breach`, `make_metrics_with_bands`.

**`test_suite/`** — 12 files, 83 tests: scenarios/projections, HQLA valuation, borrowing lines/pledges, funding concentration, EWI/posture, playbook lifecycle, playbook actions, limits/breaches, intraday, RBAC/auth, FK reverse-reachability.

**Audit results (all PASS):**
- Every §1.8 difficulty instance has ≥2 tests; every non-stub §1.9 corner instance has ≥1 test; all 4 `excluded_because` stubs verified to resolve to real difficulty instances (not translated).
- Every test carries exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` tag copied verbatim; no extra/unknown tags.
- All 151 quoted docstring spans verified verbatim against PRD.md via whitespace-normalized grep (C1/C2/C3).
- No `skip`/`skipif`/`xfail` markers; no scaffold references in generated code.
- All files compile; `pytest --collect-only` collects 83 tests cleanly.

**Two-reader relaxations applied where the PRD leaves outcome space open:** (1) executing a BLOCKED action on a suspended line accepts `ERR_INVALID_STATE` or `ERR_LINE_SUSPENDED` via `validate_error_is_one_of` (both gates are PRD-named, but their relative order at that pair is not pinned); (2) the fresh-scenario `version == 1` assertion is PRD-derived via the run-count bump arithmetic, not a naming assumption. No instances were skipped — every non-stub design instance has verbatim PRD coverage.

## Step 6: Implementation Generation — 2026-08-14T03:10:00.000Z

**Generated:** `workspace/implementation/` — Python + Flask, in-memory store (empty at boot, no seeding), 60 endpoints across `routes_core.py` / `routes_risk.py` / `routes_playbooks.py`, with `db.py` (store + logical clock pinned at 2026-08-01T00:00:00Z), `errors.py` (all 26 catalog error IDs), `responses.py` (meta/api_request_id envelope), `middleware.py` (X-User-ID/X-User-Role auth + RBAC), `helpers.py` (validation, limit/offset pagination, floor arithmetic), `services.py` (8 calculations: per-asset-floor HQLA with BASELINE/STRESS variants, CONTRACTUAL/BEHAVIORAL projection, funding concentration with lexicographic tie-break, 4-ordinal posture machine with one-step de-escalation hysteresis, pinned-order borrowing power + auto-suspension, capacity test with per-line aggregate, strict-boundary breach detection with dedupe), and `start.sh` (guarded pip install + `exec python3 app.py`, `0.0.0.0:$PORT`).

**Test-side defects found and fixed (PRD wins; per repo precedent from task_1477):**
1. `test_suite/test_04|07|08` (8 tests): removed vestigial bare `make_scenario(name="Base", tier="BASELINE")` lines immediately preceding `setup_active_drawdown_playbook`/`setup_executing_drawdown`, whose fixtures create their own ACTIVE BASELINE scenario. The dead first creation collided with the PRD §3.1 `ERR_DUPLICATE_ACTIVE_SCENARIO` rule pinned by `test_scenario_retirement_guards`; its return value was unused in all 8 tests. No behavioral assertion was touched.
2. `test_05_funding_concentration.py::test_top_counterparty_tiebreak_by_name`: the corner design's setup put Retail at 2× the tied wholesale balances, which holds the top share outright (5000 bps) under the PRD §3.5 all-counterparties formula — contradicting the instance's own 2500 bps assertion (test_09's remediation comments pin the all-inclusive formula at 5454/4000, confirming the corner's setup was the defect). Fixed the setup so Retail joins the tie at 1,000,000,000 (three-way tie, 3333 bps each, lexicographic winner "Alpha"), preserving the tie-break coverage the instance exists to verify.

**Implementation decisions pinned by tests over scaffold defaults:** (a) `POST /liquidity/funding-evaluations` returns 200, not the scaffold table's 201 — PRD §4 reserves 201 for resource creation and the evaluation is a computed read (posture-evaluations stays 201: it appends and returns a PostureSnapshot); (b) caller-supplied datetimes (`observed_at`, `snapshot_at`, and derived `last_reading_at`) are echoed verbatim, while server-stamped fields (`created_at`, `updated_at`, `finalized_at`, etc.) use the logical clock in ISO-8601 with three fractional digits — the cadence test pins `last_reading_at == "2026-08-02T00:00:00Z"`.

**Verification:** `prd-bench-local-run --test-dir test_suite --isolation per-test-server` → **83/83 passed, 0 failed, 0 errors** (fresh server boot per test via `bash start.sh`). Three independent end-to-end smoke suites (scenarios/projections/HQLA/funding; EWI cadence/posture/breach SoD lifecycle/intraday ordering; pledges/lines/draws/playbook lifecycle with release→auto-suspend→action-blocking cascade) also pass on fresh boots with hand-verified arithmetic.

## Step 7: Test-Fix Iteration Loop — 2026-08-14T03:25:00.000Z

All 8 rounds are clean: 83/83 passed in every round, 664/664 total across the sweep. No failures surfaced, so no diagnostic iterations were needed. The implementation is stable under the full parallel sweep protocol.

Summary:
- Iterations run: 1 (single 8-round parallel sweep; all 8 rounds ran to completion concurrently, joined with `wait`).
- Results: round 1–8 each passed=83, failed=0, errors=0, total=83 (664/664 aggregate). Zero flakiness — every test passed in every round.
- Tests deleted: none.
- Fixes applied to `test_helpers/`: none this iteration (prior fixes from Step 6 — tie-break setup in `test_05`, dead duplicate-BASELINE-scenario lines in `test_04/07/08` — held stable).
- Fixes applied to `test_suite/`: none this iteration.
- Fixes applied to `implementation/`: none this iteration (prior pins — HTTP 200 on `POST /liquidity/funding-evaluations`, verbatim echo of caller-supplied datetimes — held stable).

Relevant paths:
- Results: `/home/ubuntu/github/CodingPRD/tasks/task_1605_liquidity_stress_testing_contingency/workspace/implementation/results.{1..8}.json`
- Implementation: `/home/ubuntu/github/CodingPRD/tasks/task_1605_liquidity_stress_testing_contingency/workspace/implementation/`
- Test suite: `/home/ubuntu/github/CodingPRD/tasks/task_1605_liquidity_stress_testing_contingency/test_suite/`

Exit condition met: all 8 parallel rounds have `passed == total`. Task 1605 is stable.

## Step 8: PRD Finalization — 2026-08-14T03:35:00.000Z

The diff is minimal — exactly two in-place sentence revisions, no line-count change (311 → 311 lines, 0% delta; both edits replaced existing lines with longer single lines, keeping paragraph structure intact).

One final cross-check on the no-new-mismatch rule for Edit 1's "even though breach detection may ride along" phrase: the funding evaluation does run `detect_breaches` (routes_core.py:340-348) which can persist LimitBreach records. Could "persists no resource of its own" be misread as contradicting breach creation? The phrasing "no resource of its own" plus "even though breach detection may ride along with it" explicitly acknowledges that breaches may be created as a side effect while the evaluation itself is not a persisted resource — consistent with routes_core.py. Also confirmed against §3.5's existing text ("the evaluation immediately runs breach detection ... `breaches_created` counts how many new breaches were raised") — the new §4 sentence aligns with, rather than narrows, §3.5.

For Edit 2: enumerated every field the impl stamps or echoes. Server-stamped via `fmt_dt(store.clock)`: `created_at`, `updated_at` (helpers.py:62-63, 78), `finalized_at` (routes_core.py:227), `tested_at` (routes_playbooks.py:266), `activated_at` (routes_playbooks.py:306), `executed_at` (routes_playbooks.py:408) — all named in the edit's example list. Caller-echoed: `observed_at` (routes_risk.py:158), `snapshot_at` (routes_risk.py:389), `last_reading_at` (routes_risk.py:171) — all named. The edit is explicitly scoped to "datetime fields carried on a resource," so it does not mis-describe: (1) the clock endpoint's `to_iso8601` input / `current_utc` response (not a resource field; response is server-formatted), (2) `as_of_date`/`business_date` (date strings, not datetimes, already pinned as YYYY-MM-DD in §3.2/§3.7), (3) the envelope's `api_request_timestamp` (covered by §2.2, wall-clock, not a resource field), (4) `pledged_value_cents` pinning (unrelated). The phrase "such as" keeps the server-stamped list non-exhaustive so no unlisted stamped field is excluded.

Summary on exit:

**Line counts:** PRD.md = 311 lines, PRD_FINALIZED.md = 311 lines, 0% delta (two in-place line revisions; no lines added or removed).

**Changes:**
- §2.5 — revise — replaced the blanket "All timestamps are ISO 8601 UTC with three fractional digits" with a split rule: server-stamped timestamps (`created_at`, `updated_at`, `finalized_at`, `tested_at`, `activated_at`, `executed_at`) are ISO-8601 UTC with three fractional digits from the logical clock, while caller-supplied datetimes on resources (`observed_at` on readings, `snapshot_at` on intraday snapshots, and the derived `last_reading_at` on metrics) are echoed verbatim from the request payload — implementation/helpers.py:25-26,62-63,78; implementation/routes_core.py:227; implementation/routes_playbooks.py:266,306,408; implementation/routes_risk.py:158,171,389.
- §4 — revise — pinned the HTTP status of the two evaluation endpoints: `POST /liquidity/funding-evaluations` returns 200 (computed read, persists no resource of its own, breach detection may ride along), `POST /liquidity/posture-evaluations` returns 201 (appends and returns a PostureSnapshot) — implementation/routes_core.py:336-356; implementation/routes_risk.py:215-219.

**Test-side Step 7 items (no PRD edit needed):** diff items 1 and 2 (vestigial `make_scenario` fixture collisions with `ERR_DUPLICATE_ACTIVE_SCENARIO`, and the `test_top_counterparty_tiebreak_by_name` setup fix) were pure test-fixture defects. PRD §3.1 already pins the one-active-scenario-per-tier rule, and §3.5 already pins the all-counterparties concentration formula with lexicographic tie-break — implementation matches both, so the prose stays verbatim.

**Per-edit pre-edit search log:**

Edit 1 (§4, funding-evaluations 200):
- (a) Subject: HTTP status classification of POST evaluation endpoints under the §4 201-vs-200 rule.
- (b) Enumerated impl paths: all 13 `status=201` returns (routes_core.py:104,204,269,333; routes_risk.py:121,188,219,268,403; routes_playbooks.py:95,220,483,592 — every one a resource-creating POST); all 200-default POSTs (clock set, retire, finalize, capacity-test, approve, activate, stand-down, revise, complete, execute, settle, fail, suspend, reinstate, draw, repay, release, acknowledge, escalate, remediate, funding-evaluations — all state transitions, modifications, or computed reads); `responses.py:17` `ok()` default status=200; `routes_risk.py:219` posture-evaluations 201 (appends PostureSnapshot via `services.append_posture_evaluation`).
- (c) Wording adjustment: framed as "applying that rule" to the two evaluation endpoints rather than restating a new rule, and added "even though breach detection may ride along with it" so the sentence stays consistent with `detect_breaches` persisting LimitBreach records inside the funding-evaluation request (routes_core.py:340-348) and with §3.5's `breaches_created` prose.

Edit 2 (§2.5, timestamp echo):
- (a) Subject: format/echo policy for timestamp fields on resources.
- (b) Enumerated impl paths: `helpers.py:21-26` (`now_iso`/`fmt_dt`, 3-fractional-digit logical-clock format), `helpers.py:58-79` (`new_entity`/`new_event`/`touch` stamp `created_at`/`updated_at`), `routes_core.py:227` (`finalized_at`), `routes_playbooks.py:266,306,408` (`tested_at`, `activated_at`, `executed_at`), `routes_risk.py:142,158,162,169-172` (reading `observed_at` echoed via `body["observed_at"]`; `last_reading_at` copied from latest reading's verbatim string), `routes_risk.py:373,389` (`snapshot_at` echoed via `body["snapshot_at"]`), `routes_core.py:61-72` (clock endpoint: `to_iso8601` parsed, response `current_utc` server-formatted — NOT verbatim), `routes_core.py:169,191` + `routes_risk.py:372,387` (`as_of_date`, `business_date` — date strings via `req_date`, already covered by §3.2/§3.7), `responses.py:12-14` (envelope `api_request_timestamp` — wall clock, covered by §2.2).
- (c) Wording adjustments: (i) scoped the verbatim-echo claim to "caller-supplied datetime fields carried on a resource" so the clock endpoint's `to_iso8601`/`current_utc` pair (input not a resource field; response server-formatted) is not mis-described; (ii) named `last_reading_at` explicitly as derived from the latest reading's `observed_at` to match routes_risk.py:171; (iii) used "such as" for the server-stamped list to keep it non-exhaustive; (iv) replaced rather than extended the original "All timestamps..." sentence, since the blanket three-fractional-digits claim was false for the verbatim-echo fields (e.g. `"2026-08-02T00:00:00Z"` reads back without fractional digits).

PRD_FINALIZED.md is at /home/ubuntu/github/CodingPRD/tasks/task_1605_liquidity_stress_testing_contingency/workspace/PRD_FINALIZED.md.

## Step 9: PRD Completeness Scan — 2026-08-14T03:47:00.000Z

All 14 edits applied cleanly. The patch is complete and every change traces to implementation behavior.

### Summary

**Source vs output**: `PRD_FINALIZED.md` (311 lines / 49,282 chars) → `PRD_COMPLETED.md` (314 lines / 52,153 chars). Char delta: **+2,871**.

**Counts**: 14 ambiguity-pins, **0 mismatch-revisions** — PRD_FINALIZED was already behaviorally aligned with `implementation/`; every change closes a PRD silence where the implementation had adopted one specific interpretation.

Changes (all inserts; file = `/home/ubuntu/github/CodingPRD/tasks/task_1605_liquidity_stress_testing_contingency/workspace/PRD_COMPLETED.md`):

- **§2.2 Error format** — insert — ambiguity — undefined path/unsupported method → `ERR_NOT_FOUND` 404; unexpected failure → `ERR_INTERNAL` 500, same envelope — `implementation/app.py:25-35`
- **§2.3 Pagination** — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` 400; `created_at` ties broken by insertion order — `implementation/helpers.py:191-225`
- **§3.3 HQLA summary** — insert — ambiguity — `scenario_id` is a required query parameter; missing → 400, unknown → 404 — `implementation/routes_core.py:299-304`
- **§3.3 Repricing** — insert — ambiguity — replacement `market_value_cents` must be strictly positive — `implementation/routes_core.py:291`
- **§3.4 Repayment** — insert — ambiguity — repayment requires no line status; a `SUSPENDED` line accepts repayments — `implementation/routes_playbooks.py:541-548`
- **§3.5 Funding evaluation** — insert — ambiguity — empty-book case: `top_counterparty_bps` zero and `top_counterparty_name` null — `implementation/services.py:223-228`
- **§3.6 Metric creation** — insert — ambiguity — duplicate `code` → `ERR_INVALID_REQUEST` (400) — `implementation/routes_risk.py:105-106`
- **§3.6 Reading side effects** — insert — ambiguity — breach detection runs before the reading-triggered auto posture evaluation, so the new breach counts in that snapshot's `open_breach_count` — `implementation/routes_risk.py:176-186`
- **§3.6 Posture snapshot** — insert — ambiguity — automatic snapshots record `evaluated_by_user_id` as the literal string `system`; the three counts are taken before the breach-escalation cascade applies — `implementation/routes_risk.py:186`, `implementation/services.py:159-210`
- **§3.7 Remediation re-proof** — insert — ambiguity — per-subject derivation of "current value" at remediate time (latest EWI reading; fresh funding concentration; latest still-FINALIZED run across all scenarios; latest intraday snapshot), falling back to the breach's recorded `detected_value` when no current data exists — `implementation/services.py:343-372`
- **§3.7 Remediation body** — insert — ambiguity — `remediation_note` is a required field of the remediate request body — `implementation/routes_risk.py:339-340`
- **§3.8 Action creation** — revise — ambiguity — duplicate `sequence_no` within a playbook also surfaces `ERR_INVALID_REQUEST` — `implementation/routes_playbooks.py:197-201`
- **§3.8 Capacity-test result** — insert — ambiguity — failure-entry shapes: `ACTION_CAPACITY_INSUFFICIENT` (action_id, estimated_proceeds_cents, realizable_cents), `LINE_AGGREGATE_EXCEEDS_BORROWING_POWER` (line_id, summed estimate, borrowing_power_cents), `TARGET_CAPACITY_NOT_MET` (total_estimated_cents, target_capacity_cents); passing tests return the same shape with empty `failures` — `implementation/services.py:304-337`
- **§3.9 Revision** — insert — ambiguity — revise clears `tested_at` and `approved_by_user_id` but deliberately leaves `activated_at` as previously stamped — `implementation/routes_playbooks.py:339-341`
- **§5 Error catalogue** — insert — ambiguity — added `ERR_INTERNAL | 500` row matching the new §2.2 prose — `implementation/app.py:33-35`

Everything else in the implementation (RBAC, OCC ordering, projection formulas incl. per-division flooring, borrowing-power recompute order and auto-suspension cascade, strict breach-detection boundaries and dedupe, posture thresholds/hysteresis, playbook lifecycle gates, settlement timing, verbatim echo of caller datetimes, envelope shape) was already uniquely pinned by PRD_FINALIZED.md and verified against the code with no divergence.
