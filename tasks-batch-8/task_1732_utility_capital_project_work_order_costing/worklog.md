# Worklog — task_1732_utility_capital_project_work_order_costing

## Step 1: Create Task Directory — 2026-08-14T12:00:00.000Z

Pre-assigned directory `tasks/task_1732_utility_capital_project_work_order_costing/` with `workspace/` subdirectory already created by the pipeline dispatcher. Step 1 treated as DONE per command args; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T13:10:00.000Z

Scaffold generation complete. All three artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_1732_utility_capital_project_work_order_costing/` and pass `scaffold_lint.py` with **VERDICT: clean lint** (55 endpoints, 13 entities, 20 §1.8 instances, 44 active §1.9 instances + 10 excluded stubs, 762 calls scanned, zero violations). No sibling task directories were inspected.

**Files:**
- `SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — `scaffold_difficulty_design:` with all 9 rules, 20 instances (combinatorial_formula and cross_entity_state_dependency carry 3 each)
- `SCAFFOLD_CORNER_DESIGN.yaml` — `scaffold_corner_design:` across all 9 claim-guide sections, 44 active + 10 `excluded_because:` stubs

**Design summary (harder-than-expert calibration):**
- **Archetype blend:** ledger reconciliation + compliance/audit; flat topology; cyclic state machines; segregation-of-duties role model; 8 complexity layers (OCC, cascades, dual-variant calc, thresholds, derived-field reconciliation, ops-run checkpoint, feature flags, scheduled actions).
- **Intractable mechanics:** AFUDC accrual with pinned circular evaluation order (begin-balance compounding, CIAC exclusion with zero floor, HALF_MONTH vs FULL_MONTH program flag — 1,000c vs 2,000c on identical inputs); per-line overhead rounding pinned against sum-then-round (309c vs 308c); unitization waterfall with negative largest-remainder correction (50,001/20,001/30,001); NET_OF_CIAC vs GROSS_WITH_CONTRA depreciation bases with per-entry contra credits; half-month depreciation factors at in-service/retirement; amortization final-scheduled-month plug (3,333/3,333/3,334); strictly-greater 110% variance posture gate that blocks the *next* charge; 15% closeout variance gate satisfied by ≥-coverage from approved regulatory assets; period close/reopen compensation cycle reversing entry logs.
- **Key boundary pins (all literals verified by executing the formulas in Python):** exactly 110.00% allowed / 110.01% blocks; exactly 10% estimate delta routes to Controller; exactly 10,000,000c requires Controller authorize; budget equality passes; coverage equality passes; touching half-open schedule bounds don't overlap while period gaps are forbidden.
- **Two true-race OCC rules** on `WorkOrder.version` (estimate create-with-supersede, superseding approve), both exercised by sequential stale-version tests; four SoD pairings enforced via X-User-ID.

**Issues caught and fixed during self-review:** reversal accounting double-subtraction in the CWIP formula (originals now stay summed with negating REVERSAL rows); amortization plug rule (min-vs-remaining would have left 1c unamortized — switched to final-scheduled-month plug); an unreachable `ERR_RETIREMENT_BEFORE_IN_SERVICE` (removed); CIAC receive now allowed while COMPLETED to avoid a closeout deadlock; a routing-tier masking bug in one corner test (approver changed to Controller); missing `ERR_SEGREGATION_OF_DUTIES` catalog entry (added). Every one of the 34 error codes is exercised by at least one test recipe, and placeholder closure + instance-name uniqueness + grounds resolvability were mechanically verified across both design files.

## Step 3: Copy Shared Files — 2026-08-14T13:11:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1732_utility_capital_project_work_order_costing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T13:30:00.000Z

All verification gates pass. The PRD is complete.

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_1732_utility_capital_project_work_order_costing/workspace/PRD.md` (315 lines), generated solely from `SCAFFOLD.yaml` — the difficulty/corner design files were never opened.

**Document shape:** §1 introduction (2 paragraphs, business-context angle); §2.1–2.10 with domain-derived subsection titles (roles/identity, verbatim §2.2, pagination, common properties incl. the append-only ledger-entry exception, integer-cents rounding discipline, the logical clock, OCC, the 11-category validation order, flat reference checking, atomic derived balances); §3.1–3.9 grouped by lifecycle (reference data → calendar → work-order origination/authorization → estimates → charges/reversals/variance hold → CIAC → completion/cancellation/deferral → closeout/unitization → period close/reopen); §4 endpoint table (55 rows, 4 columns); §5 error catalogue (34 rows, 2 columns).

**Hard Contract Reports**

Contract 1 — Field-Name Coverage:
- entities[].fields: 116 required (incl. 4 common fields), 116 present, 0 missing
- endpoints[].request_body/input identifiers: 51 required (scaffold folds query filters into `input` with `?` suffixes), 51 present, 0 missing
- endpoints[].query_params: 0 explicit keys in scaffold; path-template params (`program_id`…`entry_id`) all present
- Status: PASS

Contract 2 — Rule Coverage:
- validations[] with priority: 11 checked, 11 expressed (§2.8 ordered list + local reinforcement in §3.3/3.4/3.5/3.8), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write operation + `expected_work_order_version` + `ERR_STALE_VERSION`/412, stale-picture framing only), 0 missing
- state_machines[].transitions: 30 checked, 30 fully expressed (all 8 machines, including both Estimate system transitions, all 6 cancel branches with the 0%/10% forfeiture split, and the period OPEN→CLOSED→REOPENED→CLOSED cycle), 0 missing
- calculations[]: 12 checked, 12 fully expressed in precise prose with all pinned worked examples (unitization 100,003-cent remainder to the TRANSFORMER line; amortization 3,333/3,333/3,334; AFUDC half- vs full-month 1,000c vs 2,000c; depreciation net 1,000c/gross 1,200c variants with the 100c contra credit; overhead 9c-per-row vs 8c-on-sum; closeout gate 100,000→116,000 example), 0 missing
- validations[] conditions: every one matchable to its error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed in workflow narratives, 0 missing
- entities[].fields[] structured content: defaults/initials/bounds reconstructible from prose, 0 missing
- sibling-branch symmetry: cancel branches, CIAC/AFUDC method variants, approve/reject decisions rendered with equal density, 0 asymmetric
- Status: PASS

Contract 3 — §3 Path Purity:
- backtick tokens scanned: 628; tokens starting with `/`: 0; bare HTTP-method tokens: 0; method+path tokens: 0
- Status: PASS

**Additional checks:** §2.2 verified byte-identical to the canonical source; §4 matches the scaffold's 55 endpoints exactly with correct roles; §5 carries all 34 error IDs with correct HTTP statuses; all 50 enum/state values appear verbatim; prose scan found zero fuzzy words and zero pseudocode operators. One authoring gap was caught and fixed during the walk: work-order authorization as a `variance_posture` recompute trigger (now stated in §3.3).

## Step 5: Generate Unit Tests — 2026-08-14T14:10:00.000Z

Test infrastructure and suite generation is complete for task_1732.

## What was generated

**`test_helpers/`** (Stage 1) — 9 modules under `/home/ubuntu/github/CodingPRD/tasks/task_1732_utility_capital_project_work_order_costing/test_helpers/`:
- `types.py` — all 13 entity TypedDicts (append-only AFUDC/depreciation/amortization entries correctly omit `updated_at`/`version` per PRD §2.4) + 15 status/domain enums
- `api_client.py` — `ApiClient(GenericApiClient)` with all 56 endpoints under `/ucp` (including the test-driving clock)
- `api_errors.py` — all 34 `ApiErrorId` members with the §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + ledger/budget invariant checkers (`cwip = actual_direct + afudc_total`, `available = authorized - committed`)
- `factories.py`, `constants.py` — input-only payload factories; domain thresholds (110% variance, 10% routing, 10,000,000c authorize tier, 10% forfeiture, 15% closeout tolerance), standard 2026-08/09/10 period payloads
- `test_users.py` — all-opaque role headers for the 10 operator ids (admin-1…aud-1) + `make_headers(role, user_id)` for SoD cross-role scenarios
- `fixtures.py` — composite lifecycle builders: `create_in_progress_work_order`, `setup_charging_world`, `setup_completed_work_order`, `setup_closed_work_order`/`setup_unitized_transformer_world`, `setup_variance_hold_world`, `setup_closeout_overrun_world` (the PRD §3.8 116,000-vs-100,000 worked instance), CIAC/reg-asset helpers, entry-list readers; OCC versions always read live

**`test_suite/`** (Stage 2) — `conftest.py` + 8 test files, **84 tests collected**:
`test_01_reference_data_and_calendar`, `test_02_work_order_lifecycle`, `test_03_estimates_occ_and_routing`, `test_04_authorization_budget_and_access`, `test_05_charges_overhead_and_variance`, `test_06_period_close_accruals`, `test_07_cancellation_ciac_and_regulatory_assets`, `test_08_closeout_unitization_and_retirement`.

## Verification results

- **Coverage audit**: 20/20 difficulty instances have ≥2 tests; 44/44 non-stub corner instances have ≥1 test; all 10 `excluded_because:` stubs resolve to real difficulty instances and were not translated.
- **Citation sweep**: every test's docstring carries verbatim PRD quotes (each verified to contain a ≥8-word window that literal-greps in `PRD.md`) and ends with exactly one `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` tag copied from the YAML `name:` fields. All 34 asserted error IDs are named in PRD prose (§2/§3), not just the §5 table.
- **Hygiene**: no `skip`/`skipif`/`xfail` markers; no scaffold references in comments/docstrings; pyflakes clean; `pytest --collect-only` collects all 84 tests.

## Two PRD-derivability narrowings (documented gaps, not weakened tests)

1. `work_order_creation_seeds_estimate_and_defaults` — the instance's `version == 1` sub-assertion was dropped: PRD §2.4 never pins the initial version value (only relative +1 increments, which are asserted elsewhere). Everything else (DRAFT, zeroed counters, seed estimate seq 1/PROPOSED/eng-1, `req_` prefix) is verbatim-covered and asserted.
2. `expense_order_lifecycle_no_capitalization` — `capitalizable_total_cents == 0` was dropped for the EXPENSE closeout: PRD §3.8's capitalizable formula has no EXPENSE carve-out, so two PRD-only readers diverge on the value. The PRD-pinned outcomes are all asserted: 10% O&M loading (11,000c total), zero AFUDC entries, CLOSED with an empty unitization list, zero FixedAssetUnits.

## Step 6: Generate Implementation — 2026-08-14T14:15:00.000Z

Done. The implementation for task_1732 is complete and passes the full test suite: **84/84 tests passed** under `prd-bench-local-run --isolation per-test-server` (server restarted via `start.sh` before every test, 0 failed/errors).

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_1732_utility_capital_project_work_order_costing/workspace/implementation/` — Python + Flask, in-memory store, no seeding:

- **`start.sh`** — guarded install (no-op once Flask is importable), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000); verified fresh-boot with empty store.
- **`app.py`** — entry point, `ApiError` handler, 404/405 mapping to `ERR_NOT_FOUND`.
- **`db.py`** — 13 entity collections + insertion-sequence counter (created_at tiebreak).
- **`errors.py`** — all 34 catalog error IDs with exact HTTP statuses.
- **`response.py`** — scaffold envelope: `meta`/`response_type`/`data`, pagination fields in `meta` for lists, two-field `meta` on errors.
- **`middleware.py`** — `X-User-Role` (one of 7 roles) required on all endpoints; `X-User-ID` required on mutating endpoints; 401/403 split.
- **`validate.py` / `util.py`** — shape validators, logical clock (default `2026-08-01T00:00:00Z`, never wall-clock), Decimal-based round-half-up helpers.
- **`services/core.py`** — all derived balances (CWIP, committed, capitalized, contra, remaining, variance posture, available) computed from the ledger at read time, so close/reopen compensation can never drift; `touch()` bumps `version`/`updated_at` per PRD §2.10; snapshot fields stored at closeout/cancel.
- **`services/period_close.py`** — the 5-step close (AFUDC → depreciation → amortization → CIAC sweep → seal) and compensating reopen.
- **`routes/`** — 12 modules covering all 55 endpoints.

## Key fidelity decisions (traced to PRD prose)

- **AFUDC begin-balance**: pinned examples (1,000c vs 2,000c on 200,000c at 1%) forced `begin_cwip` = prior periods' charges + prior ACCRUED AFUDC, excluding the closing period's own charges — matching "each period's begin is the prior period's end."
- **Pinned rounding**: per-row overhead (3×100c@2.5% → 9c), unitization waterfall (100,003 → 50,001/20,001/30,001 with remainder to greatest-target TRANSFORMER), amortization plug (3,333/3,333/3,334), half-month depreciation factors, GROSS_WITH_CONTRA contra credits (606c entry → 100c credit), all verified live.
- **Validation order §2.8** enforced everywhere, including the subtle ones: OCC (6) before state (7) on estimate create/approve; tier (5) before OCC; SoD (8) before budget/variance (11); closeout variance gate last. One ordering bug (missing-`expected_work_order_version` shape check must precede the tier check on approve) was caught in self-review and fixed.
- **Boundary rules**: strictly-greater 110% variance hold (110.00% stays within), inclusive 10% routing tier, exactly 10,000,000c requires Controller, coverage equality passes the closeout gate, touching half-open schedule bounds don't overlap, strict period adjacency.
- **CIAC lifecycle**: lazy expiry with EXPIRED flip on the failed receive (422 + persisted side effect), 0%/10% forfeiture split by cancel state, creation-order waterfall application at closeout with excess refund.
- **Literal-spec quirks honored**: cancellation from AUTHORIZED+ does not withdraw PROPOSED estimates; EXPENSE orders still set `capitalizable_total_cents` and roll into `capitalized_actual_cents`; ledger entries carry only `id`/`created_at`.

Two independent end-to-end smoke suites (lifecycle, AFUDC compounding with CIAC offset, reopen/re-close cycles, retirement NBV, all guard errors) also pass, and per-test-server reboots were exercised 84 times by the runner with no restart flakiness.

## Step 7: Run Tests and Iterate — 2026-08-14T14:25:00.000Z

# Summary

**Exit condition met: clean 8-round parallel sweep.**

- **Iterations run:** 1 (no fixes needed — the sweep passed on the first attempt)
- **Results:** All 8 rounds report `passed=84/84, failed=0, errors=0`. Every test passed in every round with no flakiness signal across the union of rounds.
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `implementation/`:** none.

**Verification details:** I read the full PRD (`workspace/PRD.md`, 315 lines), all 13 implementation modules (~2,700 lines across `workspace/implementation/routes/`, `services/`, and the top-level support modules), and the test artifact layers (`test_helpers/` fixtures/factories/assertions/constants/users plus the 8 `test_suite/` files) while the sweep ran. Spot-checks confirmed alignment between layers:

- Validation priority order in the routes matches PRD §2.8 verbatim (auth → permission → existence → shape → tier → OCC → state → SoD → temporal → referential → fiscal), e.g. `authorize_work_order` evaluates tier → state → SoD → approved-estimate → budget in that exact order.
- The pinned rounding discipline (PRD §2.5) is implemented per-row via exact `Decimal`/`rhu_div` arithmetic, including the closeout unitization waterfall with its negative-remainder landing rule and tie-break chain (target → standard_cost → asset_class alphabetical), matching the PRD's worked example.
- Segregation-of-duties identity model is consistent: `test_helpers/test_users.py` uses distinct opaque operator ids per role (`eng-1` vs `sup-1` vs `ctrl-1`) so PRD-required SoD checks are satisfiable, with `make_headers` exposed for same-id-different-role scenarios.
- Ledger-entry resources (AFUDC/depreciation/amortization) serialize with only `id` + `created_at`, matching PRD §2.4's append-only carve-out.
- Storage is in-memory dicts only (`db.py`), so per-test-server `start.sh` restarts guarantee fresh state.

No diagnostic action was required; the task is complete.

## Step 8: Finalize PRD — 2026-08-14T14:26:00.000Z

SKIPPED per the Step 8 skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond baseline. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` is produced.

## Step 9: Complete PRD — 2026-08-14T14:45:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1732_utility_capital_project_work_order_costing/workspace/PRD_COMPLETED.md` produced as a minimal patch over `PRD.md`.

**Size:** PRD.md 315 lines / 61,871 chars → PRD_COMPLETED.md 315 lines / 63,819 chars (char-delta +1,948; all changes inline, no new lines or sections).

**Counts:** 19 ambiguity-pins, 0 mismatch-revisions. Every endpoint, state transition, formula, guard order, error pair, response shape, filter, and default in `implementation/` was walked against the PRD; all PRD-pinned behaviors (validation order §2.8, tiers, thresholds, rounding discipline, waterfall tie-breaks, worked examples, error catalogue, endpoint table) matched implementation exactly, so nothing required revision.

**Changes (one bullet each):**

- §2.3 — insert — ambiguity — out-of-envelope pagination input (`limit` not an integer / outside 1–100, `offset` non-integer or negative) rejected with `ERR_VALIDATION` — routes/helpers.py:11-33
- §2.3 — insert — ambiguity — `created_at` sort ties break by creation (insertion) order; unit lists apply the `line_no` tiebreak before that fallback — routes/helpers.py:46-54, db.py:26-32, routes/units.py:31
- §2.4 — insert — ambiguity — `version` starts at 1 on creation and `updated_at` initially equals `created_at` — services/core.py:45-55
- §2.6 — insert — ambiguity — logical clock keeps whole-second resolution; fractional seconds in `to_iso8601` are truncated — util.py:50-52,68-70
- §3.1 — insert — ambiguity — closing a program that is not `OPEN` is rejected with `ERR_INVALID_STATE` — routes/programs.py:75-77
- §3.3 — insert — ambiguity — `initial_estimated_cost_cents` is not retained as a work-order field; it lives only on the seeded estimate — routes/work_orders.py:51-84, services/core.py:333-362
- §3.3 — insert — ambiguity — return `reason` is required but not persisted on the work order — routes/work_orders.py:127-133
- §3.5 — insert — ambiguity — reversal row copies `overhead_rate_pct` from the original and records the reversing clerk as `posted_by_user_id` — routes/charges.py:126,130
- §3.7 — insert — ambiguity — auto-created Regulatory Asset's `description` is system-generated as `Cancelled work order write-off: {title}` — routes/work_orders.py:245
- §3.7 — insert — ambiguity — a `writeoff_disposition` supplied while `cwip_cents` is zero is accepted but not recorded (`cancel_writeoff_disposition` stays unset) — routes/work_orders.py:236-241
- §3.8 — insert — ambiguity — omitted `unitization_lines` reads as an empty array; each line's `quantity` must be an integer ≥ 1 — routes/work_orders.py:336-350
- §3.8 — insert — ambiguity — closeout CIAC application proceeds in agreement creation order, each `RECEIVED` agreement applying `min(received, gross CWIP still unabsorbed)` — routes/work_orders.py:402-412
- §3.8 — insert — ambiguity — an agreement applied at closeout keeps `forfeited_cents` unset (null) — routes/work_orders.py:404-412 (field never set on this path)
- §3.8 — insert — ambiguity — each Fixed Asset Unit also records the line's `unit_catalog_id` and `quantity` — routes/work_orders.py:424-427, services/core.py:421-437
- §3.9 (Step 1) — insert — ambiguity — AFUDC beginning CWIP is the carry-in balance from prior periods only (charges attributed to earlier periods plus still-accrued AFUDC), excluding the closing period's own charge rows — services/period_close.py:56-69
- §3.9 (Step 1) — insert — ambiguity — `amount_cents` is computed from the exact base (which may end in a half cent under HALF_MONTH); the recorded `base_cents` is the base itself rounded half up — services/period_close.py:76,83
- §3.9 (Step 2) — insert — ambiguity — CIAC contra credit is zero whenever the order's gross CWIP is zero (ratio undefined) — services/period_close.py:124-129
- §3.9 (Step 3) — insert — ambiguity — an amortization entry that is simultaneously the first and the zeroing one (e.g. a one-month term) moves the asset directly `APPROVED` → `FULLY_AMORTIZED` — services/period_close.py:172-175
- §3.9 (reopen) — insert — ambiguity — the step-4 CIAC sweep is not compensated by a reopen; agreements flipped to `EXPIRED` remain `EXPIRED` — services/period_close.py:223-262 (reopen reverses only entries/balances)
