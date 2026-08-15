# Worklog — task_1809_value_based_contract_settlement_quality

Scenario: 1809. Value-Based Contract Settlement & Quality Withhold (payer value-based programs). Difficulty directive: harder than expert level.

## Step 1: Create Task Directory — 2026-08-14T17:53:00.000Z

Directory `tasks/task_1809_value_based_contract_settlement_quality/` and `workspace/` pre-created by the pipeline invoker (index 1809 assigned externally). Verified present.

## Step 2: Generate Scaffold — 2026-08-14T19:20:24.120Z

Subagent summary (verbatim):

All three artifacts are complete and clean. Final state of the work:

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1809_value_based_contract_settlement_quality/`):
- `SCAFFOLD.yaml` (104 KB) — §1.0–§1.7 only; no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (110 KB) — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (270 KB after re-serialization) — single top-level key `scaffold_corner_design`

**Verbatim lint verdict** (`scaffold_lint.py`, final run):
```
Coverage
  §1.5 endpoints declared:    96
  §1.1 entities declared:     17
  §1.8 instances scanned:     18
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  1813

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Summary counts**
- Entities: 17 (flat topology under `/vbc`, all FKs canonical `FK -> X.id`, all reverse-reachable)
- State machines: 17 (incl. cyclic Settlement FINALIZED→DISPUTED→RECALCULATING→PROVISIONAL→FINALIZED, QualityMeasureResult validate↔correction loop, PerformanceYear reopen cycle, remittance return/requeue cycle)
- Calculations: 13 (chained: member-months → attribution rollup/RAF (dual-variant PROSPECTIVE/CONCURRENT) → cost with stop-loss → shared savings/loss with MSR/MLR corridor + caps → quality composite (INTERIM/OFFICIAL variants) → gate multiplier (floor/slide/excellence) → withhold release (per-claim rounding pinned) → settlement net (8-step pinned order) → interim estimates (ANNUALIZATION vs COMPLETION_FACTOR, reserve accrual) → largest-remainder distribution → renewal recommendation)
- Validations: 14 ordered priorities (auth → role → existence → group scope → request shape → state → safety/SoD → temporal → overlap → referential → uniqueness → fiscal → quality-math → OCC)
- Endpoints: 96
- Errors: 63
- Roles: 11 (10 opaque + PracticeGroupRep entity_backed:PracticeGroup; segregation_of_duties model enforced via `finalized_by_user_id` vs resolver `X-User-ID`)
- Concurrency rules: 3 OCC rules (attribution-run/interim-report/renewal-analysis create-with-supersede), each with a stale-version corner test
- §1.8 instances: 18 (9 rules × 2, all non-stub, all with structured replayable chains)
- §1.9 instances: 62 (0 stubs; sections: entities 10, state_machines 11, calculations 11, validations 12, endpoints 3, errors 4, rbac 5, complexity_layers 5, consistency_model 1)

**Key design adjudications**
1. Flat topology (prioritized per §0.3 diversity guidance); every entity gets single-GET + filtered-list GET so all FKs pass reverse-reachability.
2. Attribution modeled as explicit roster records on supersede-able runs (no visit-plurality graph) — keeps attribution deterministic; ties in distribution resolved by `Practice.created_at ASC`, never `id`.
3. `ERR_DISPUTE_ALREADY_OPEN` was designed, then deleted as unreachable: an open dispute forces settlement DISPUTED, so the FINALIZED state precondition subsumes it (state check fires first).
4. Quality composite is observable only through Settlement (OFFICIAL) and InterimReport (INTERIM) — the dual-variant divergence is proven via the interim input-set corner (VALIDATED result counted vs REPORTED result excluded, identical claims, est_net 95,000 → 0).
5. `ERR_QUALITY_RESULTS_UNLOCKED` was initially referenced but undeclared — caught by the error-closure audit, added to catalog plus a dedicated corner instance.
6. Rounding pinned everywhere adversarially: per-claim withhold round_half_up-then-sum (3×10¢ → 3, not 2), per-record benchmark round-then-sum, savings rate truncated toward zero, distribution floor + largest-remainder with literal remainder cents (78,333/39,167) and a created_at tie-break corner (50,244/50,243).
7. Logical clock endpoint carries the mandatory default `2026-08-01T00:00:00Z`; all window math (runout 90d, dispute filing 30d, resolution 60d) is clock-driven with boundary-exact recipes (finalize at exactly period_end+90d succeeds; dispute filed at finalized_on+31d fails).
8. Two full-pipeline renewal journeys (~45 calls each: program → … → DISTRIBUTED → CLOSED → EXPIRED → analysis → renew) anchor the deepest chains, one ending RENEW_RENEGOTIATE at realized rate exactly 99 bp, one DO_NOT_RENEW at −277 bp blocking renew.
9. All formula-derived asserts were pre-computed by executing the formulas in Python and transcribing literals (no expression asserts).

## Step 3: Copy Shared Files — 2026-08-14T19:20:40.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes). No subagent.

## Step 4: Generate PRD — 2026-08-14T19:31:27.218Z

Subagent summary (verbatim):

All three hard contracts pass. The PRD is complete at 445 lines.

---

## Report

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_1809_value_based_contract_settlement_quality/workspace/PRD.md` (445 lines, ~74 KB)

### Section structure
- **§1. Introduction** — 3 paragraphs setting up the VBC settlement domain and its adversarial workload.
- **§2. Global Specifications & System-Wide Principles** — 11 subsections: §2.1 RBAC (11 roles, opaque vs entity-backed identity), §2.2 verbatim response envelope, §2.3 Pagination, §2.4 Logical Clock (startup default `2026-08-01T00:00:00Z`), §2.5 Common Resource Properties, §2.6 Precision/Rounding/Sign Conventions (round-half-up vs truncate-toward-zero vs floor), §2.7 OCC (3 guarded creates), §2.8 Validation Cascade (14 priority levels), §2.9 Nested Resource Retrieval, §2.10 `needs_recompute` Cascade Contract, §2.11 Risk-Model Pinning.
- **§3. Business Logic & Workflows** — 13 subsections organized by lifecycle stage: §3.1 Programs/Groups/Practices, §3.2 Members/EligibilitySpans, §3.3 Contract Terms/Activation, §3.4 Performance Years, §3.5 Attribution Runs/Records, §3.6 Risk Scores/Attribution Rollup, §3.7 Claims/Cost Measurement/Withhold Pool, §3.8 Quality Measure Reporting, §3.9 Interim Reports/Reserve Accrual, §3.10 Settlement Computation/Finalization, §3.11 Disputes/Recalculation, §3.12 Distribution Remittances/Largest-Remainder Waterfall, §3.13 Renewal Analysis/Contract Renewal.
- **§4. Endpoint Definitions** — 96-row table (Method, Path, Description, Authorized Roles).
- **§5. Error Code Catalogue** — 63-row table (Error ID, HTTP Status).

### Coverage audit (scaffold → PRD)
- 17 entities → §3.1–§3.13 narratives; field names embedded in prose
- 17 state machines → §3 transition pairs (all 61 transitions named with `FROM → TO` arrows)
- 13 calculations → §3.5 (member_months), §3.6 (attribution_rollup, risk_model_variant), §3.7 (cost_measurement, withhold_pool), §3.8 (achievement_points), §3.10 (quality_composite, quality_gate_multiplier, shared_savings_and_loss, settlement_net), §3.9 (interim_estimate), §3.12 (distribution_allocation), §3.13 (renewal_recommendation)
- 14 validations (priority cascade) → §2.8 enumerated list
- 3 concurrency rules → §2.7 OCC subsection
- 96 endpoints → §4 table
- 63 errors → §5 table, each triggered in §2/§3 prose
- 11 roles → §2.1 + endpoint authorization column
- response_envelope → §2.2 verbatim, §2.3 pagination

### Hard Contract reports
```
Field coverage check:
- entities[].fields + endpoints[].input + path params: 125 required, 125 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 14 checked, 14 expressed in §2.8 in priority order
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id named)
- state_machines[].transitions: 61 checked, 61 fully expressed with FROM → TO arrows + error IDs + side effects
- calculations[]: 13 checked, 13 fully expressed with formulas, rounding, and constants narrated
- validations[] conditions: all matched to error_id in prose
- endpoints[].side_effects: expressed in relevant workflow narratives
- sibling-branch symmetry: exclude/reinstate, withdraw/expire, UPHELD/OVERRULED, ACTIVE/SUSPENDED → TERMINATED all rendered at equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 687
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

### Zero-Silence-Rule decisions
1. **`needs_recompute` cascade** — scaffold distributes the flag-set logic across many side_effect bullets; I centralized the contract in §2.10 and referenced it from each trigger point in §3 so a PRD-only reader sees the unified invariant.
2. **Mid-month rule constant** — scaffold constant `MID_MONTH_DAY: 15` is rendered as "the 15th of that month" in §3.5 with the closed-interval comparison explicitly stated.
3. **Completion-factor table** — the 11-entry `COMPLETION_MILLI` constant is enumerated verbatim in §3.9 ("150 for month 1, … 995 for month 11").
4. **Renewal thresholds** — `RENEW_MIN_SAVINGS_BP: 100` and `QUALITY_DROP_TOLERANCE: 5` are embedded in §3.13 as "at least 100 basis points" and "not dropped by more than 5 points (greater than or equal to -5)".
5. **Sliding-scale base** — `SLIDING_BASE_BP: 5000` is rendered as the literal 5000 in §3.10 step four.
6. **Default risk score** — `DEFAULT_SCORE_MILLI: 1000` is rendered as "the default of 1000 milli (a neutral 1.000 risk factor)" in §3.6.
7. **§3.13 cross-reference fix** — corrected a reference from §3.11 to §3.13 for the renewal flow (renewal analysis lives in §3.13, disputes in §3.11).
8. **Status-field naming** — the scaffold's `*_status` field identifiers (`program_status`, `group_status`, etc.) are mentioned explicitly as backticked field names at entity-creation time, separate from the UPPERCASE state values that flow through transitions; this keeps Contract 1 (field-name coverage) and state enumeration coverage independent and auditable.

## Step 5: Generate Unit Tests — 2026-08-14T20:32:09.625Z

Subagent summary (verbatim):

All audits pass. The suite is complete. Here is the summary.

## Task 1809 test generation — complete

**Output:**
- `test_helpers/` (9 files): `types.py` (17 entity TypedDicts + 17 status/role enums), `api_client.py` (71 endpoint methods on `GenericApiClient`), `api_errors.py` (63 error IDs + HTTP map registered with the framework), `assertions.py` (per-entity structural asserts + `assert_year_rollups` / `assert_settlement_chain`), `factories.py` (payload builders incl. canonical contract terms and measure catalogs), `constants.py` (clock dates, thresholds, PRD-derived expected values), `test_users.py` (11 roles; `make_practice_group_rep_headers(group_id)` for the entity-backed role), `fixtures.py`, `__init__.py` barrel.
- `test_suite/`: `conftest.py` + 10 test files, **98 tests**, all collecting cleanly under `pytest --collect-only` and pyflakes-clean.

**Coverage:** Queue A — all 18 difficulty instances, ≥2 tests each (36 tests). Queue B — all 62 corner instances, 1 test each. Zero instances skipped; zero `skip`/`xfail` markers. Every docstring carries verbatim-grep-verified PRD citations (automated check: all pass) and ends with exactly one `Design:` line resolving to a real instance (automated check: 80/80 tags resolve, no bogus tags).

**Helper architecture:** the load-bearing piece is `fixtures.py`'s `build_pipeline(org, stage=...)` — a 13-rung ladder (SETUP → OPEN → RUN_LOCKED → ATTRIBUTION_LOCKED → MEASURING → RECONCILING → SETTLEMENT → FINALIZED → AUTHORIZED → DISTRIBUTED → SETTLED → CLOSED → EXPIRED) over `setup_org()` (program/group/practices/members/spans), with parameterizable claims (per-claim pay clocks), risk scores, quality specs, contract overrides, and optional interim publish. `single_member_journey` / `canonical_two_member_journey` wrap the two canonical populations. OCC-guarded creates always re-read the parent version; dispute helpers thread `X-User-ID` identity (so-1 finalizer vs adj-9 adjudicator vs group-scoped rep).

**Design-to-PRD mismatches adjudicated (all resolved to PRD-derived literals):**
1. **Composite-denominator bug class** — instances asserting "composite 30 / multiplier 5000" on the single-measure journey (HBA1C 350/1000, w10000) used the full catalog weight as denominator; PRD §3.10 sums weights over the input-set results only, giving composite 33 → multiplier 5300. Corrected: net 70,000 → **74,200** in `remittance_approve_requires_group_active`, `dispute_resolution_window_elapsed_then_expire`, `practice_group_rep_scope_violation_forbidden`, `practice_group_rep_files_and_withdraws_own_dispute`, `immediate_consistency_readback_after_finalize`; net 72,500 → **76,850** in `stale_settlement_finalize_rejected_then_recalculated`; reserve 31,250 → **33,125** in `reserve_accrual_released_on_mark_settled`; report-A est_net/reserve 95,000/47,500 → **100,700/50,350** in `interim_variant_input_filtering_changes_estimate`.
2. **risk_model divergence** — the CONCURRENT benchmark 1,859,400 was RAF-driven; PRD §3.6 pins per-record round-then-sum → **1,860,000** (RAF 1033 unchanged).
3. **interim estimate divergence** — the COMPLETION_FACTOR side ignored its own savings_cap_bp 800 (cap 144,000 binds); PRD §3.10 gives est_net **77,000**, reserve **38,500** (355,000/396,177 divergence preserved as 355,000 ≠ 77,000).
4. **Hidden window constants** — DISPUTE_WINDOW_DAYS / DISPUTE_RESOLUTION_DAYS / RECONCILIATION_RUNOUT_DAYS are symbolic in the scaffold and absent from the PRD. I kept every asserted rule but re-anchored clocks to window-length-invariant outcomes: finalize 2027-06-01 (months past period_end), file/resolve one day after their anchor, window-closed/elapsed actions a full year past. Date-stamp assertions follow the actual clock per PRD stamp rules.
5. **eligibility_span_inverted_range_rejected** — dropped the instance's "start == end accepted" branch (contradicts PRD §2.8 step 12 "strictly before" and the scaffold's own `start >= end` condition); kept the 422 rejection.
6. **performance_year_list_filter_and_pagination** — PRD §2.3 defines only `limit`/`offset`; per-endpoint filters are scaffold-only, so filter assertions were dropped (pagination meta + envelope asserted on the unfiltered 3-year list). The same adjudication replaced all recipes' filtered GETs with unfiltered list + client-side matching.
7. **settlement_exists_second_create_rejected** — dropped `settlement_seq == 2` for the post-VOID successor (PRD pins only "starting at 1 for the first non-VOID settlement"); the ERR_SETTLEMENT_EXISTS → reopen → recreate rule is fully asserted.

## Step 6: Generate Implementation — 2026-08-14T20:32:09.625Z

Subagent summary (verbatim):

Implementation complete and verified. Final summary:

## What was built

A complete Python + Flask implementation of the VBC Settlement & Quality Withhold API at `/home/ubuntu/github/CodingPRD/tasks/task_1809_value_based_contract_settlement_quality/workspace/implementation/` — all 96 endpoints, 17 entities, 17 state machines, 63 error codes, in-memory only, no seeding. Verified against ~150 hand-replayed checks derived from the task's design files, including every pinned numeric journey (settlement chain 117,500 net; interim estimates 355,000/396,177 + reserves 177,500/198,089; largest-remainder 78,333/39,167 and tie-break 50,244/50,243; RAF floor 1166; stop-loss truncation vs pre-truncation withhold; dispute recalc cycle; renewal metrics; OCC 412s; cascade priority pairs).

## File layout

- `start.sh` (exec-launches `app.py`, guarded `pip install` on `import flask, waitress`), `requirements.txt` (flask, waitress)
- `app.py` — app factory, 16 blueprints, ApiError/404/405/500 handlers, global RLock around each request (atomic cascades under concurrent OCC probes); waitress on `0.0.0.0:$PORT` (default 10000)
- `db.py` — 17 entity dicts keyed by id, logical clock (default exactly `2026-08-01T00:00:00Z`), UUIDs, monotonic wall-clock `created_at`/`updated_at` (3-fractional-digit ISO), `touch()` (unconditional bump for direct mutations) vs `apply_updates()` (change-detecting bump for cascades, per PRD §2.5's "a mutation is any change to any field")
- `errors.py` — full 63-code catalog with HTTP map; `response.py` — exact `meta`/`response_type`/`data` envelope, pagination fields `limit/offset/total_count/has_more` (defaults 10/0, min 1, max 100); `middleware.py` — header auth (priority 1), role check (2), `PracticeGroupRep` group-scope check (4); `util.py` — shape validators, exact integer rounding primitives
- `routes/*.py` — 16 modules, one per resource group; `services/calculations.py` — all 13 calculation rules; `services/engine.py` — cascade primitives

## Store architecture

Plain dicts keyed by UUID. Every entity carries `id/created_at/updated_at/version` (version starts 1, +1 per mutation, exactly 1 for lifecycle transitions with folded-in rollup recomputes). Logical clock drives only business date stamps (`paid_on`, `filed_on`, `published_on`, `finalized_on`, `review_started_on`, `resolved_on` — all ISO dates) and window arithmetic; `created_at`/`updated_at` use a strictly monotonic wall-clock timestamp so creation order is always recoverable (required by the distribution tie-break, which the corner tests exercise without advancing the logical clock).

## Calculation module

`services/calculations.py` implements: mid-month member-months (15th-of-month, closed-span coverage, ACTIVE spans only); attribution rollup (per-record `round_half_up(pmpm×mm×score/1000)` summed — pinned order; RAF = floor of weighted mean, `None` on empty population; FINAL-score fallback to `DEFAULT_SCORE_MILLI` 1000); cost measurement (per-member stop-loss min) vs withhold pool (per-claim round-half-up pre-truncation); achievement points (`rate_bp` round-half-up, `>=` thresholds); composite (OFFICIAL=LOCKED, INTERIM=VALIDATED+LOCKED); gate multiplier (0 / sliding 5000+rhupart / 10000 with pinned boundaries); shared savings/loss (rate truncated toward zero, MSR `>=`, MLR `<= -x`, cap=min of two independently rounded terms, zero corridor, benchmark==0 guard); the pinned 8-step settlement chain; interim estimates (both variants always computed, `estimate_method` selects, `COMPLETION_MILLI` table, reserve = `rhu(max(0,est_net)×months/12)`); largest-remainder distribution (floor, remainder cents by fractional part DESC with `Practice.created_at` ASC ties, conservation); renewal metrics (truncated realized rate, latest−earliest composite/RAF, `RENEW_*` thresholds 100bp/−5pts, `>=`).

## Validation cascade

Each route evaluates in strict priority order: (1) headers → (2) role → (3) path ids then body-FK existence → (4) PracticeGroupRep scope → (5) shape (required/unknown fields/types/enums/scalar ranges birth_year 1900–2026, score_milli 1–10000, months_elapsed 1–11) → (6) from-state and state-family preconditions (includes `ERR_SETTLEMENT_STALE` before the runout check, `ERR_YEARS_NOT_CLOSED` before term-ended, etc.) → (7) segregation-of-duties / risk-model pin → (8) temporal windows → (9) overlap (half-open years, closed spans) → (10) attribution referential five-parter in declared order → (11) uniqueness family → (12) fiscal/rate/date-range (422) → (13) quality math guards (422) → (14) OCC `expected_<parent>_version` (412). Verified priority pairs: temporal>fiscal on claim create, state>temporal on authorize-distribution, existence>state on void, stale>runout on finalize.

## Ambiguities resolved

1. **Window constants unpinned in PRD/scaffold** — the PRD names `DISPUTE_WINDOW_DAYS`, `DISPUTE_RESOLUTION_DAYS`, `RECONCILIATION_RUNOUT_DAYS` without values. The task's dated corner recipes pin them exactly: **30** (finalized 2027-04-01 + 30d closes 2027-05-01), **60** (filed 2027-04-10 + 60d ends 2027-06-09), **90** (period_end 2027-01-01 + 90d = 2027-04-01). All comparisons per PRD: filing `<=`, resolve `<=`, mark-settled/authorize/expire strict `>`, runout `>=`.
2. **Composite denominator** — PRD prose says "sum of weight_bp over the same results," but the design's pinned `interim_variant` literals (est_net 95,000 with only HBA1C w9000 validated out of a 10,000-weight catalog) are only satisfiable with the **catalog-wide** weight sum; I implemented catalog-wide (documented in the module). With no qualifying results, numerator 0 → composite 0 either way, so the empty-set guard is preserved.
3. **Two design-file arithmetic slips (unsatisfiable by any monotone formula, so PRD fidelity chosen):** (a) single-measure 3-point composites are hand-computed as 30 in four corners (stale/reserve/immediate/rep-withdraw), but the PRD-pinned formula `rhu(num×100/(9×den))` yields 33 — the formula is corroborated by the design's own weighted-composite (31) and canonical (30) asserts; (b) the CONCURRENT benchmark 1,859,400 uses floored-RAF multiplication, contradicting the PRD's pinned per-record-round-then-sum (1,320,000+540,000=1,860,000) and the design's own raf_floor assert (2,100,000). My implementation follows the PRD formula in both cases.
4. **Void vs mark-paid cascade asymmetry** — mark-paid cascades only when the year is "past MEASURING" (RECONCILING+); void's transition side effects carry no such qualifier, so void always recomputes/stales/flags.
5. **Unspecifiable uniqueness errors** — `dispute_ref` per settlement and attribution-record member-per-run uniqueness have no error IDs in the 63-code catalog and are unreachable in practice (second dispute filing is blocked by `ERR_SETTLEMENT_NOT_FINAL` once DISPUTED); not enforced.
6. **Recalculate on a non-stale PROVISIONAL settlement** — allowed (idempotent recompute + flag clear); the PRD only pins the stale-gated finalize path.
7. **Clock endpoint response** — echoes the supplied `to_iso8601` string verbatim as `current_utc`.
8. **Renewal successor `contract_ref`** — set to `ref + "-R"` without re-running uniqueness (renew must not 409 on its own derived ref).

### Orchestrator note for Step 7 (known cross-agent divergence)

The Step 5 and Step 6 subagents resolved one PRD ambiguity in OPPOSITE directions — the quality-composite **denominator** when the composite's input set is narrower than the contract catalog:
- Tests (Step 5) assert the PRD-§3.10 reading "sum of weight_bp over the same results" → denominator = sum of weights over the input-set results only → e.g. `interim_variant_input_filtering_changes_estimate` expects est_net 100,700 / reserve 50,350.
- Implementation (Step 6) chose the catalog-wide weight sum to match the design index's pinned literals → produces est_net 95,000 / reserve 47,500 for that scenario.
Expect exactly this class of failure in the first sweep; adjudicate per the STEP 1/2 protocol against the verbatim PRD §3.10 sentence.

## Step 7: Run Tests and Iterate — 2026-08-14T20:49:20.159Z

Subagent summary (verbatim):

All 8 rounds verified clean independently: `passed == total == 98`, `failed == 0`, zero non-passed tests, files timestamped 20:42 (post-fix sweep — the sweep-2 command deleted the stale result files before launching). Task complete.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (baseline → fix → verification). Baseline: 92/98 in all 8 rounds, 6 deterministic failures (union = identical set in every round). Verification sweep: **98/98 in all 8 rounds**.

**Tests deleted:** None. Every failing test traced to a PRD-verbatim, uniquely-derivable rule.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1809_value_based_contract_settlement_quality/test_helpers/fixtures.py` — `build_pipeline`: merged `contract_overrides` over the default `contract_ref` parameter instead of passing both to `make_contract`. The duplicate-kwarg `TypeError` blocked 4 tests (`test_risk_model_prospective_variant_drives_benchmark`, `test_risk_model_concurrent_variant_diverges`, `test_interim_estimate_annualization_authoritative`, `test_interim_estimate_completion_factor_diverges`) whose overrides legitimately carry distinct `contract_ref`s (PRD §2.8 step 11 requires `contract_ref` unique within a program when two pipelines share one org).

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1809_value_based_contract_settlement_quality/test_suite/test_08_disputes.py` — `test_practice_group_rep_files_and_withdraws_own_dispute`: added `set_clock(CLOCK_DISPUTE)` before the inline dispute filing (plus the `CLOCK_DISPUTE` import). The test asserted `filed_on == "2027-06-02"` but never advanced the clock past `CLOCK_FINALIZE` (2027-06-01); PRD §3.11 pins `filed_on` to the logical clock, so the setup — not the implementation — was wrong.

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1809_value_based_contract_settlement_quality/workspace/implementation/services/calculations.py` — `compute_composite`: denominator changed from catalog-wide `sum(weight_of.values())` to the input-set sum `sum(weight_of.get(r["measure_code"], 0) for r in results)`. PRD §3.10 verbatim: "the denominator is the sum of the `weight_bp` values over the same results", and the zero-guard clause "If the denominator is zero — **no locked results**, or all weights somehow zero" uniquely determines this reading (catalog weights are required strictly positive, so only an empty input set can zero the denominator). This resolves the known cross-agent divergence in the tests' favor: composite 33 / multiplier 5300 on single-measure journeys, est_net 100,700 / reserve 50,350 on the interim-variant instance. No previously-passing test could regress — the two readings coincide unless the variant's input set is a strict subset of the catalog, which only that one corner test exercises.

## Step 8: Finalize PRD — 2026-08-14T20:53:47.829Z

Subagent summary (verbatim):

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1809_value_based_contract_settlement_quality/workspace/PRD_FINALIZED.md` is written with exactly one minimal patch.

## Summary

**Line counts / delta:** PRD.md = 444 lines / 74,226 chars; PRD_FINALIZED.md = 444 lines / 74,390 chars. Delta: +164 chars (+0.221%), 0 line delta (the single edit extends an existing paragraph in place).

**Changes (one total):**
- **§3.10 (Settlement Computation and Finalization, "Third" step) — insert** — appended one sentence to the composite paragraph: *"In both variants the numerator and the denominator are each summed over exactly the results that variant includes, never over the contract's whole measure catalog."* This pins the input-set denominator for both the OFFICIAL (LOCKED-only) and INTERIM (VALIDATED+LOCKED) composite variants — the paragraph previously defined the denominator ("sum of the `weight_bp` values over the same results") inside a paragraph grammatically scoped to the official variant, and defined the interim variant only by its closing "includes both `VALIDATED` and `LOCKED` results" sentence, leaving the interim denominator's input set under-determined (the exact catalog-wide vs input-set divergence Step 7 resolved in the impl). — `implementation/services/calculations.py:189-212` (denominator at line 209; callsites at lines 286 official / 358 interim).

**Step 7 items with no PRD edit (justification):**
- `test_helpers/fixtures.py` `build_pipeline` — pure fixture bug (duplicate-kwarg `TypeError`); no implementation behavior involved.
- `test_suite/test_08_disputes.py` clock fix — pure test bug; PRD §3.11 already pins `filed_on` to the logical clock verbatim, so prose kept as-is.

**Per-edit pre-edit search log (mandatory):**
- (a) **Subject:** the input set over which the quality-composite numerator and denominator are summed, for both variants.
- (b) **Impl paths enumerated and read/grepped:** `services/calculations.py:189-212` (`compute_composite`: official→{LOCKED}, interim→{VALIDATED,LOCKED}; num=Σ `achievement_points`·weight over the set; den=Σ weight over the same set; `den==0 → 0`; else `rhu(num*100, 9*den)`); both callsites — `calculations.py:286` (official, via `compute_settlement_chain`, reached from `routes/settlements.py:85` create, `:128` finalize, `:142` recalculate, and `routes/disputes.py:179` UPHELD auto-recalc via `services/engine.py:89-99`) and `calculations.py:358` (interim, via `compute_interim_estimates` ← `routes/interim_reports.py:67`); `calculations.py:447-459` (`compute_renewal_metrics` reads only *stored* `quality_composite_points`, no denominator logic); `gate_multiplier` (pure function of points); `routes/contracts.py:129-130` (catalog `weight_bp` strictly positive) and `routes/quality.py:70-72` (results must reference catalog codes), confirming den==0 ⟺ empty input set so the existing zero-guard sentence remains accurate; PRD cross-references at lines 95, 217, 225, 237, 269 (none redefine the denominator; all consistent).
- (c) **Wording adjustment:** reused §3.9/§3.10's own "includes" terminology ("the results that variant includes") and scoped the new sentence strictly to numerator+denominator input sets — no claims about the zero-guard, rounding, storage, or renewal — so every enumerated path, including off-site ones (renewal reading stored composites, dispute-driven recalc), remains accurately described.

## Step 9: Complete PRD — 2026-08-14T21:14:16.561Z

Subagent summary (verbatim):

Done. PRD_COMPLETED.md is complete and verified. Final summary:

## Summary

**Source vs output**: `PRD_FINALIZED.md` 444 lines / 74,657 chars → `PRD_COMPLETED.md` 444 lines / 80,618 chars (char-delta **+5,961**; all edits in-paragraph, no new sections, line count unchanged). 31 edit operations across 33 diff lines (two edits each spanned two paragraphs).

**Counts**: 19 ambiguity-pins (insert), 12 mismatch-revisions (revise). File refs are under `/home/ubuntu/github/CodingPRD/tasks/task_1809_value_based_contract_settlement_quality/workspace/implementation/`.

### Ambiguity-pins (PRD silent → pinned to impl)

- §2.1 — insert — ambiguity — PracticeGroupRep on settlement/dispute **list** endpoints is silently restricted to own-group resources before pagination (not 403) — routes/settlements.py:97-98, routes/disputes.py:124-125
- §2.3 — insert — ambiguity — non-integer limit/offset, limit outside 1..100, negative offset → `ERR_INVALID_REQUEST` (400) — util.py:23-50
- §2.3 — insert — ambiguity — `has_more` true iff `offset` + returned items < `total_count` — response.py:35
- §2.3 — insert — ambiguity — per-endpoint exact-match conjunctive query filters enumerated (all 17 list endpoints) — util.py:64-70 + every route's `apply_filters` call
- §2.4 — insert — ambiguity — clock response echoes `to_iso8601` verbatim as `current_utc`; stored value normalized to UTC; naive timestamp interpreted as UTC — routes/clock.py:23, util.py:168-181
- §2.4 — insert — ambiguity — `created_at`/`updated_at`/`api_request_timestamp` are strictly-monotonic wall-clock; business date stamps (`paid_on`, `filed_on`, `published_on`, `review_started_on`, `resolved_on`, `finalized_on`) and window decisions read the logical clock date — db.py:60-66, 86-93
- §2.5 — insert — ambiguity — cascades that change no field value perform no version bump (conditional touch) — db.py:111-121
- §2.7 — insert — ambiguity — successful OCC-guarded create increments the parent's `version` by 1 (resolves the previously dangling "parent-bumping cascades named in §2.7" reference in §2.5) — routes/attribution.py:95, routes/interim_reports.py:87, routes/contracts.py:356
- §2.7 — insert — ambiguity — requests serialized: each request incl. cascades runs to completion before the next begins — app.py:30-65
- §2.8 step 5 — insert — ambiguity — `numerator_count`/`denominator_count` non-negative; date fields strict `YYYY-MM-DD` — routes/quality.py:61-62, util.py:148-159
- §2.8 step 8 — insert — ambiguity — added `ERR_CONTRACT_TERM_NOT_ENDED` (contract expiry at/after `effective_end`) to the temporal family — routes/contracts.py:253-254
- §3.3 — insert — ambiguity — `renewed_from_contract_id` is null on a directly drafted contract — routes/contracts.py:190
- §3.4 — insert — ambiguity — year rollups start at 0 / `risk_adjustment_factor_milli` and `locked_run_id` null at creation — routes/performance_years.py:86-93
- §3.5 — insert — ambiguity — record `member_months` is 0 until run compute — routes/attribution.py:214
- §3.6 — insert — ambiguity — empty/zero-member-month population ⇒ `total_member_months` 0, RAF null, `benchmark_cost_cents` 0 — services/calculations.py:110-112
- §3.7 — insert — ambiguity — voiding does not clear `paid_on` — routes/claims.py:151-152
- §3.9 — insert — ambiguity — "YTD withhold pool" defined as per-claim round-half-up over the YTD claim set (not the year's stored `withhold_pool_cents`); both estimate variants, `est_net_payable_cents`, `reserve_accrual_cents` computed once at creation, frozen at publish — services/calculations.py:351, routes/interim_reports.py:66-88
- §3.10 — insert — ambiguity — `settlement_seq` = max over all of the year's settlements **including VOID** + 1 — routes/settlements.py:72-75
- §3.4/§3.10/§3.11 — insert — ambiguity — window constants pinned: 90-day reconciliation runout ("at or after"), 30-day dispute window (filing "on or before"; mark-settled/authorize "strictly greater"), 60-day resolution window (resolve "on or before"; expire "strictly greater") — services/calculations.py:31-33
- §3.10 — insert — ambiguity — recalculate permitted on any PROVISIONAL settlement whether or not `needs_recompute` is set — routes/settlements.py:136-145
- §3.11 — insert — ambiguity — UPHELD combined DISPUTED→RECALCULATING→PROVISIONAL cascade advances settlement `version` by exactly 1 — routes/disputes.py:175-182
- §3.12 — insert — ambiguity — remittances created in ascending `Practice.created_at` order; straight-to-DISTRIBUTED generalized to "no remittances created" (net ≤ 0 **or** zero total weight) — services/calculations.py:418-426, routes/settlements.py:176-180
- §3.13 — insert — ambiguity — realized savings rate defined as 0 when the summed benchmark is zero — services/calculations.py:442-443
- §3.13 — insert — ambiguity — successor `contract_ref` ("-R" suffix) applied unconditionally, bypassing the §2.8 uniqueness check — routes/contracts.py:294-300
- §4 — insert — ambiguity — undefined route → 404 `ERR_NOT_FOUND`; defined route with unsupported method → HTTP 405 carrying `error_id` `ERR_INVALID_REQUEST` — app.py:71-77

### Mismatch-revisions (PRD said X, impl does Y → revised to impl)

- §2.5 — revise — mismatch — year-transition version list missed open-attribution and close; now all seven — routes/performance_years.py:138-139, 229-230, 262-263
- §2.8 step 12 — revise — mismatch — spans allow `start_date == end_date` (one-day span); only contracts/years require strictly-before — routes/members.py:133-135
- §3.3 — revise — mismatch — expiry checks years-CLOSED (`ERR_YEARS_NOT_CLOSED`) before term-ended (`ERR_CONTRACT_TERM_NOT_ENDED`) — routes/contracts.py:250-254
- §3.4 — revise — mismatch — "five year transitions" (listing six, omitting close) → seven transitions incl. close — routes/performance_years.py (every transition calls `db.touch`)
- §3.4 — revise — mismatch — begin-reconciliation preconditions "evaluated together" → "evaluated in the order listed" (period-end → population → quality) — routes/performance_years.py:188-197
- §3.5 — revise — mismatch — removed "Records are unique per member per run" (impl enforces no such uniqueness; duplicate members contribute independently) — routes/attribution.py:167-219 (no check present)
- §3.7 — revise — mismatch — cost recompute triggers: mark-paid only once the year is past MEASURING (RECONCILING or later; PAST_MEASURING set), every void, finalize/recalculate, and the UPHELD auto-recalculation; a MEASURING-time mark-paid leaves stored totals untouched — routes/claims.py:37, 124-127, 153-157; services/engine.py:81-99
- §3.10 — revise — mismatch — finalize gates evaluated stale-check (`ERR_SETTLEMENT_STALE`) first, then the 90-day runout — routes/settlements.py:117-124
- §3.10 — revise — mismatch — "Recalculate is the only way to clear the flag" scoped to settlements remaining PROVISIONAL (the UPHELD cascade also clears it) — routes/disputes.py:180
- §3.11 — revise — mismatch — resolve preconditions in cascade order: segregation-of-duties **before** the resolution window (matches §2.8 priorities 7 < 8) — routes/disputes.py:162-167
- §3.11 — revise — mismatch — removed "`dispute_ref` unique within the settlement" (impl enforces no uniqueness; it's a free label) — routes/disputes.py:84-85 (no check present)
- §4 table — revise — mismatch — recalculate row: "with needs_recompute set" → "whether or not needs_recompute is set" — routes/settlements.py:139-141

All pipeline-note leads were verified and pinned (window constants with operators, non-stale recalculate, clock verbatim echo, "-R" uniqueness bypass, wall-clock-vs-logical clock split, list filters, pagination 1..100 bounds with 400 rejection, 404/405 handlers, per-request serialization). Tests were used only as cross-reference (e.g., they deliberately avoid pinning window lengths, confirming the constants were PRD-silent).
