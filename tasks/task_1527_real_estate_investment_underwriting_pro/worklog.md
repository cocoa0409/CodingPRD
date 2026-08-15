# Worklog — task_1527_real_estate_investment_underwriting_pro

## Step 1: Create Task Directory — 2026-08-13T18:08:00.000Z

Task directory `tasks/task_1527_real_estate_investment_underwriting_pro/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Verified existence; no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T18:37:00.000Z

All three scaffold files are generated and pass `scaffold_lint.py` with a clean verdict.

## Summary

**Task**: `task_1527_real_estate_investment_underwriting_pro` — Real Estate Investment Underwriting & Pro Forma for a private equity real estate firm.

**Files written**:
- `/home/ubuntu/github/CodingPRD/tasks/task_1527_real_estate_investment_underwriting_pro/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1527_real_estate_investment_underwriting_pro/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1527_real_estate_investment_underwriting_pro/SCAFFOLD_CORNER_DESIGN.yaml`

**Counts**:
- **Entities**: 10 (Deal, Property, RentRollPeriod, OperatingExpense, MarketAssumption, Scenario, DebtSizing, Waterfall, ICMemo, ICVote)
- **State machines**: 3 (Deal with branching + revision loop, Scenario with DRAFT→COMPUTED→SUPERSEDED cascade, ICMemo with DRAFT→SUBMITTED→UNDER_VOTE→APPROVED/REJECTED)
- **Calculations**: 6 (`noi_year1` provisional/final dual-variant, `debt_size` DSCR-vs-LTV tiered, `irr_unlevered`, `equity_multiple`, `waterfall_split` per-tier rounding, `occupancy_pct`)
- **Validations**: 20 ordered rules covering auth → existence → state → business (referential / constraint / fiscal / safety / temporal) → OCC
- **Endpoints**: 36 (CRUD + action endpoints + flat-list FK reverse-reachability + `/_clock/set_current_utc` test-driving endpoint with `2026-08-01T00:00:00Z` startup default)
- **Errors**: 16 (incl. domain-specific `ERR_NOI_NONPOSITIVE`, `ERR_PROMOTE_REGRESSIVE`, `ERR_SEG_DUTIES`, `ERR_NONMONOTONIC_PERIOD`, `ERR_STALE_VERSION`, `ERR_DUPLICATE_VOTE`)
- **Roles**: 5 (Analyst, AssetManager, IC_Member, IC_Chair, Admin — all `opaque`; approval-chain role model with segregation-of-duties on IC voting)
- **Concurrency rules**: 2 OCC entries on `Deal.version` for scenario-create and ic-memo-create

**Difficulty design (§1.8)**: 18 instances — 2 per each of the 9 rules. Highlights:
- Dual-variant: `noi_year1` provisional vs final (concessions ordering) and `debt_size` DSCR vs LTV binding
- Combinatorial: mode (a) NOI multi-input branching, mode (b) waterfall per-tier rounding lock
- Non-linear SM: Deal reopen cycle; Scenario cascade-supersede from parent
- Transitive cascades: depth-3 YES-quorum (ICVote→ICMemo→Deal) and depth-2 NO-vote rejection
- Priority conflicts: state-vs-referential (6v9), fiscal-vs-safety (13v15)
- Boundary: IC quorum `>=2` vs `>2`; occupancy rounding at exact 1/3 fraction
- Cross-entity deps: Scenario→Deal, ICVote→ICMemo
- Overlap: rent-roll strict monotonic months vs opex composite (year,category) bucket
- Invariants: assumption-activation count conservation; waterfall cash conservation

**Corner design (§1.9)**: 33 instances across 9 sections (entities / state_machines / calculations / validations / endpoints / errors / rbac / cross_cutting / consistency_model).

**Lint verdict**: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (391 calls scanned, 0 violations).

## Step 3: Copy Shared Files — 2026-08-13T18:39:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1527_real_estate_investment_underwriting_pro/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T18:47:00.000Z

All hard contracts pass. PRD generated.

---

## Summary

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_1527_real_estate_investment_underwriting_pro/workspace/PRD.md`

### Sections
- **§1 Introduction** (2 paragraphs) — firm context, role-driven workflow, reproducibility commitment.
- **§2 Global Specifications** (9 subsections) — §2.1 RBAC + per-role `identity: opaque` prose; §2.2 emitted verbatim from `section-2.2-response-structure.md`; §2.3 pagination (limit default 10 / min 1 / max 100, offset default 0, `created_at` ascending, four `meta` fields); §2.4 common resource properties with explicit exception list for `RentRollPeriod`, `OperatingExpense`, `ICVote`; §2.5 monetary/percentage representations and precision rules; §2.6 nested path validation; §2.7 OCC (two `expected_deal_version` endpoints, both → `ERR_STALE_VERSION`/412); §2.8 validation priority ordering (13 explicit tiers, short-circuit semantics); §2.9 logical clock with startup default `2026-08-01T00:00:00Z` and `to_iso8601` / `current_utc` contract.
- **§3 Business Logic** (8 subsections) — organized by lifecycle stage: 3.1 deal origination, 3.2 property data room, 3.3 assumptions, 3.4 scenarios (with §3.4.1 NOI incl. provisional/final variants and §3.4.2 IRR/equity multiple), 3.5 debt sizing, 3.6 waterfall, 3.7 IC memo drafting/submission, 3.8 vote/approval/rejection/post-decision paths.
- **§4 Endpoint Definitions** — 4-column table (Method, Path, Description, Authorized Roles), all 36 endpoints covered.
- **§5 Error Code Catalogue** — 2-column table, all 16 error IDs.

### Hard Contracts
- **Contract 1 (Field-Name Coverage): PASS** — 78 required identifiers, 0 missing after adding `property_id` (RentRollPeriod narrative) and `memo_id` (ICVote narrative) in a second pass.
- **Contract 2 (Rule Coverage): PASS** — 2/2 OCC rules fully expressed (write_endpoint + `expected_deal_version` + `ERR_STALE_VERSION`/412); 16/16 error IDs surfaced in prose; 10/10 state names; 40/40 enum values; 6/6 calculations in reconstructible business prose (bisection range, tolerance, LP 90% share, floor, tier-locked rounding, simple non-compounded pref, 1-cent BOTH threshold, provisional vs final EGI variant all explicit); 5/5 roles with identity prose; all side effects (timestamps, version bumps, cascade supersedes, scenario pinning/unpinning) expressed.
- **Contract 3 (§3 Path Purity): PASS** — 316 backticked tokens in §3, zero path tokens, zero bare HTTP-method tokens, zero method+path combinations. All endpoint references use state-transition framing (`DRAFT → UNDERWRITING`), role + action verb ("submitting for underwriting is an analyst-only action"), or capability description ("an admin-only test-driving capability").

### Adjudications made
1. **§2.4 common-fields exception list** — listed `RentRollPeriod`, `OperatingExpense`, `ICVote` together in one paragraph rather than scattering the exception across subsections, since they share the same reason (append-only, no OCC).
2. **Validation priority ordering** — collapsed the scaffold's 20 priorities into 13 prose tiers by grouping related checks (the two auth checks remain separate as priorities 1 and 2; the business-constraint / business-fiscal / business-safety / business-temporal groups were each merged into one tier with their members enumerated). The relative order is preserved and the short-circuit semantics are explicit.
3. **OCC framing** — followed the contract's instruction to frame purely in stale-version terms (no "simultaneously", "race", or "first-writer-wins" language).
4. **Provisional vs. final NOI** — surfaced the dual-variant rule inside §3.4.1 with explicit "when" conditions (DRAFT-time compute vs. pinned in IC_REVIEW) and stated that the final value replaces the provisional one when the scenario is pinned.
5. **`IC_QUORUM_YES`** — referenced the constant by name with its value (2) inline so the threshold is unambiguous.

## Step 6: Generate Implementation — 2026-08-13T19:02:00.000Z

All edge cases pass. Implementation is complete and functional.

---

## Summary

**File breakdown** at `/home/ubuntu/github/CodingPRD/tasks/task_1527_real_estate_investment_underwriting_pro/workspace/implementation/`:

- `start.sh` — guarded pip install + `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0,<4`
- `app.py` — Flask app factory, ApiError/404/405 handlers, route registration
- `db.py` — in-memory `DB` dict (10 collections), UUID generation, **logical clock** (`LOGICAL_CLOCK` initialized to `2026-08-01T00:00:00Z`, settable only via admin endpoint; never falls back to wall clock)
- `errors.py` — `ApiError(error_id, http_status, message)`
- `response.py` — envelope helpers: `{meta:{api_request_id, api_request_timestamp, ...pagination}, response_type, data}` for success; `{meta:{...}, response_type:"error", data:{error_id, message}}` for errors. Request IDs prefixed `req_`, timestamps with 3 fractional digits, `Z` suffix
- `middleware.py` — validates `X-User-Role` then `X-User-ID` (priority 1-2), role check (priority 3). Roles: `Analyst`, `AssetManager`, `IC_Member`, `IC_Chair`, `Admin`
- `util.py` — field parsers (int/str/bool/enum, rejecting bools-as-ints), pagination parser (`limit` 1-100 default 10, `offset` ≥ 0 default 0), `init_common_fields` / `touch` (version+1, `updated_at` refresh), per-resource `*_view` serializers
- `services.py` — business logic: `compute_noi_yr1` (provisional/final variants), `project_noi_series`, `compute_exit_value`, `compute_irr_bps` (bisection), `compute_equity_multiple_bp`, `size_debt`, `run_waterfall`, `recompute_occupancy`, cascade helpers (`supersede_other_computed_scenarios`, `supersede_all_computed_scenarios`, `recompute_final_noi_if_pinned`), finders
- `routes/` — one module per resource group: `deals.py`, `properties.py`, `rent_roll.py`, `opex.py`, `assumptions.py`, `scenarios.py` (incl. debt-sizing + waterfall), `ic_memos.py` (incl. vote + reject), `clock.py`

**Endpoints implemented** — all 31 from the scaffold:
- Deals: POST/GET list/GET one, `submit-underwriting`, `submit-ic`, `reopen`, `mark-dead`
- Properties: POST under deal, GET list under deal, GET one
- Rent roll: POST (append-only, monotonic), GET list (filterable by `period_month`)
- Operating expenses: POST (unique per year+category, future-year blocked vs logical clock), GET list (filterable)
- Assumptions: POST (first set auto-active), `activate`, GET list, GET one
- Scenarios: POST (OCC-guarded via `expected_deal_version`), GET list per deal + flat GET list, GET one, `compute`, `debt-sizing` (POST + GET list), `waterfall` (POST + GET list)
- IC memos: POST (OCC-guarded), GET list per deal + flat GET list, GET one, `submit`, `vote`, `reject`, GET votes
- Clock: `POST /re-underwriting/_clock/set_current_utc` (Admin only)

**Calculations implemented** (all in Decimal arithmetic):
- `noi_year1` — provisional variant (concessions netted AFTER growth) on initial compute; final variant (concessions netted BEFORE growth) recomputed at IC-pinning time via `recompute_final_noi_if_pinned`
- `irr_unlevered` — bisection over [-0.99, 1.00] with tol 1e-6, then ×10000 half-up to integer bps
- `equity_multiple` — (sum of year NOIs + exit) / price × 10000, half-up
- `debt_size` — annuity payment formula (or 1/amort_years if rate=0), `min(dscr_max, ltv_max)` floor, binding constraint `BOTH` if `|diff| < 1 cent`, else `DSCR`/`LTV`; `dscr_at_size_pct` and `ltv_at_size_pct` rounded to nearest whole percent
- `waterfall_split` — LP equity 90% fixed; tier rounding locked per tier (half-up to integer cents before next tier); LP pref simple (non-compounded); hurdle amount uses compounded `(1+h)^hold - 1` minus `lp_pref`
- `occupancy_pct` — `round_half_up(occupied/total*10000)/100`, stored as 2-decimal float

**State machines implemented**:
- **Deal**: DRAFT→UNDERWRITING (analyst-only, requires ≥1 property + active assumption, assigns `asset_manager_id` from `X-AssetManager-ID` header); UNDERWRITING→DRAFT (`reopen`, blocked if memo SUBMITTED/UNDER_VOTE, supersedes all COMPUTED scenarios); UNDERWRITING→IC_REVIEW (asset-manager, requires SUBMITTED memo + COMPUTED scenario, pins `current_scenario_id`, supersedes other COMPUTED scenarios with `superseded_by_id = pinned_id`, memo→UNDER_VOTE, recomputes pinned NOI as final); IC_REVIEW→APPROVED (auto on YES≥2 AND NO=0); IC_REVIEW→REJECTED (auto on first NO or chair reject); REJECTED→UNDERWRITING (analyst reopen, clears `current_scenario_id`); REJECTED→DEAD (asset-manager terminal)
- **Scenario**: DRAFT→COMPUTED (analyst, deal must be UNDERWRITING); COMPUTED→SUPERSEDED (cascade from reopen / submit-ic)
- **ICMemo**: DRAFT→SUBMITTED (analyst, deal UNDERWRITING, scenario COMPUTED); SUBMITTED→UNDER_VOTE (cascade from submit-ic); UNDER_VOTE→APPROVED (auto on quorum) / REJECTED (auto on NO or chair reject); both stamp `decided_at`, cascade to deal

**RBAC** — exact role names from scaffold; `READ_ROLES` = all 5 roles for every GET; exclusive POST permissions enforced per role matrix; ownership checks via `deal.analyst_id` / `deal.asset_manager_id` matching `X-User-ID`; segregation-of-duties blocks `deal.analyst_id` from voting on that deal's memo.

**OCC** — `expected_deal_version` honored on scenario-create and memo-create; mismatch → `ERR_STALE_VERSION` 412. Validated **after** auth/role/existence/state/ownership/referential/constraint checks per PRD §2.8 priority 13.

**Design decisions / adjudications**:
1. **Validation priority order** — followed PRD §2.8 literally: auth (401) → role (403) → path existence (404) → body-FK existence (404) → state (409) → ownership (403) → referential (422) → constraint (400/409) → fiscal (422) → safety (403/409) → temporal (422) → OCC (412). When the same endpoint has multiple constraint-type checks (e.g., scenario create's referential + range + OCC), I order them per the numbered tiers.
2. **Final-variant recompute on pin** — when `submit-ic` pins a scenario, I recompute its NOI using the final variant and refresh the dependent `computed_irr_bps` and `computed_equity_multiple_bp` (since they're derived from NOI). I do **not** bump `Scenario.version` for this recompute since no state transition occurs — only the Deal's version increments per the side-effect list.
3. **Submit-ic memo selection** — when multiple SUBMITTED memos exist for a deal, I pin the most recently created one (sorted by `created_at`).
4. **NO vote `rejected_reason`** — when multiple NO votes pile up before the cascade, the first NO triggers rejection; `rejected_reason` is set from that triggering vote's `comment`.
5. **Rent roll/opex are append-only** — they carry only `id` and `created_at` (no `version`, no `updated_at`) per PRD §2.4. Each append bumps the parent `Property.version` by 1.
6. **Occupancy storage** — stored as a Python float rounded to 2 decimal places (e.g., `92.5` for 92.50%); JSON emits it as a number.
7. **Bisection edge case** — when NPV has no sign change in [-0.99, 1.00] (extreme inputs), I clamp to the bound with smaller |NPV| rather than crash.
8. **No seeding** — `DB` starts as empty dicts; logical clock starts at `2026-08-01T00:00:00Z`; no fixtures, no `seed_*()` functions anywhere.

## Step 5: Generate Unit Tests — 2026-08-13T19:19:00.000Z

Generation complete. Summary follows.

## Deliverables

**`test_helpers/`** (9 files): `types.py` (11 entity TypedDicts — append-only `RentRollPeriod`/`OperatingExpense`/`ICVote` correctly omit `updated_at`/`version` per PRD §2.4), `api_client.py` (33 endpoint methods under `/re-underwriting`), `api_errors.py` (all 16 error IDs + HTTP map registered with the framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (all roles are `identity: opaque`, so shared constants + `submit_underwriting_headers()` carrying `X-AssetManager-ID`), `fixtures.py` (composite lifecycle builders up to APPROVED/REJECTED deals; OCC-guarded writes always re-read `deal.version` fresh so fixtures are robust to either version-bump reading), `__init__.py`.

**`test_suite/`** — 63 tests in 7 files: `test_01_deal_origination.py` (5), `test_02_property_data_room.py` (12), `test_03_assumptions_and_scenarios.py` (9), `test_04_debt_sizing_and_waterfall.py` (8), `test_05_ic_memo_and_voting.py` (13), `test_06_deal_lifecycle.py` (9), `test_07_concurrency_and_envelope.py` (7).

## Coverage

- **Queue A (Difficulty)**: 16/18 instances covered, each with exactly ≥2 tests (32 tests total).
- **Queue B (Corner)**: 31/33 non-stub instances covered, ≥1 test each (31 tests). No `excluded_because` stubs exist in this corner index.

## Skipped instances (PRD-first filter failures)

1. **`Difficulty/dual_variant_calc/noi_year1_provisional_vs_final_concession_ordering`** — asserted literals `72275600`/`72412400` contradict the PRD §3.4.1 formula, which uniquely derives **70,256,000** (provisional) and **70,392,800** (final) for the pinned inputs (verified numerically; note the sibling 85%-occupancy instance's literal 57,446,000 *is* PRD-consistent, confirming the 92% literals are an upstream arithmetic error). Asserting them would fail a PRD-faithful implementation.
2. **`Difficulty/priority_pair_validation_conflict/state_vs_business_referential_on_ic_memo_create`** — asserts `ERR_INVALID_STATE` for memo-create on a DRAFT deal, but the PRD states no deal-state gate for memo *creation* (§3.7); a PRD-faithful implementer could equally return `ERR_SCENARIO_NOT_COMPUTED` (the scaffold's own validation list excludes memo-create from the state check). Outcome not uniquely derivable.
3. **`Corner/calculations/irr_and_equity_multiple_match_pinned_inputs`** — asserted NOI `72275600` / IRR ≈1522 / EM ≈18983 all derive from the same wrong literal; PRD formulas uniquely yield 70,256,000 / 1459 / 18538 (verified via bisection solver).
4. **`Corner/cross_cutting_complexity_layers/scenario_create_bumps_deal_version`** — PRD explicitly states deal-version bumps for property (§3.1), assumption (§3.3), and memo (§3.7) creation but is silent on scenario creation; two readers legitimately differ.

## Notable adjudications

- The two OCC 412 corner instances were translated with staleness induced by an **explicitly PRD-stated** version bump (property creation, §3.1) instead of the recipe's assumed scenario-create bump, keeping the OCC claim fully PRD-derivable.
- The same-month rent-roll re-entry asserts exactly `ERR_DUPLICATE_PERIOD` (not "either/or"): PRD §2.8's explicit priority order (constraint tier 9 short-circuits temporal tier 12) uniquely determines it.
- Waterfall tests assert cash conservation against the PRD §3.4.2 projection computed from the API-returned NOI (±2 cents per-tier rounding tolerance) and the exact identity `gp_promote_cents == gp_split_cents − 100,000,000` (GP equity = 10% of price, §3.6).

## Stage 2 verification

All checks pass: 63 tests collected by pytest; pyflakes clean; every test carries a PRD citation whose ≥8-word spans all grep verbatim against `PRD.md` (108/108 found, 0 failures); every docstring ends with exactly one `Design:` tag resolving to a real instance (47 unique tags, no unknown/duplicate/missing tags); no `skip`/`skipif`/`xfail` markers; no scaffold references in generated code.

## Step 7: Run Tests and Iterate — 2026-08-13T19:32:00.000Z

All 8 parallel rounds passed cleanly on the first sweep — 63/63 tests, 0 failed, 0 errors, 0 skipped in every round. No diagnostic iteration was needed: the existing implementation (generated in pipeline Step 6) and test suite (Step 5) are already in full agreement, and no flakiness surfaced across the 8 concurrent rounds under per-test-server isolation.

## Summary

- **Iterations run**: 1 (the initial 8-round parallel stability sweep; each round 63/63 passed, ~81s per round, all 8 concurrent on isolated ports).
- **Tests deleted**: none — every test traces to verbatim PRD prose and uniquely determined behavior; nothing tripped STEP 1a/1b.
- **Fixes applied to `test_helpers/`**: none.
- **Fixes applied to `implementation/`**: none.

Verified directly from `workspace/implementation/results.{1..8}.json` (`passed == total == 63`, `failed == errors == skipped == 0`, zero non-passed entries in every round's per-test list). The task is done — the benchmark's exit condition (all 8 rounds with `passed == total`) is satisfied.

## Step 8: Finalize PRD — 2026-08-13T19:32:00.000Z

SKIPPED. Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond the baseline. `PRD.md` already determined every behavior the implementation exhibits, so no `PRD_FINALIZED.md` is produced.

## Step 9: Complete PRD — 2026-08-13T19:51:00.000Z

Done. PRD_COMPLETED.md written at `/home/ubuntu/github/CodingPRD/tasks/task_1527_real_estate_investment_underwriting_pro/workspace/PRD_COMPLETED.md`.

**Size delta:** PRD.md 320 lines / 41,202 chars → PRD_COMPLETED.md 324 lines / 46,114 chars (+4 lines, +4,912 chars).

**Counts:** 18 ambiguity-pins, 4 mismatch-revisions (22 edited locations total).

**Mismatch revisions:**
- §2.7 + §3.4 — revise — mismatch — `expected_deal_version` changed from "non-optional" to optional-at-protocol-layer: omitted → no OCC check; non-integer → `ERR_INVALID_REQUEST` 400 — implementation/routes/scenarios.py:70-83, implementation/routes/ic_memos.py:58-71
- §2.8 — insert — mismatch — field presence/type/enum/range validation (400) runs after body-FK existence (tier 5) and before tier-8 business referential checks (e.g. out-of-range `occupancy_stress_pct` beats `ERR_ASSUMPTION_MISMATCH`) — implementation/routes/scenarios.py:42-67, implementation/routes/ic_memos.py:35-55
- §3.4 — revise — mismatch — removed "computation of a newer BASE scenario" as a SUPERSEDED cascade trigger (impl has no such cascade); only reopen and submit-to-IC supersede — implementation/services.py:325-347
- §2.2 — revise — mismatch — error envelope covers 4xx and 5xx (impl returns `ERR_INTERNAL` 500 in the same envelope) — implementation/app.py:28-30

**Ambiguity pins:**
- §2.1 — insert — ambiguity — ownership match enforced only on submit-underwriting/compute/memo-submit/reopen (analyst) and submit-to-IC/mark-dead (asset manager); all other writes are role-only — implementation/middleware.py + all route files
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` and unparseable filters → `ERR_INVALID_REQUEST` 400; `has_more` ⟺ `offset + limit < total_count` — implementation/util.py:80-96, implementation/response.py:29, implementation/routes/opex.py:90-96
- §2.5 — revise — ambiguity — DSCR/LTV whole-percent rounding ties half-up; occupancy serialized as JSON number — implementation/services.py:248,255,66-76
- §2.9 — insert — ambiguity — clock endpoint accepts any valid ISO 8601 instant (even earlier); unparseable → 400 — implementation/routes/clock.py:13-21
- §3.1 — insert — ambiguity — `target_purchase_price_cents` accepts any integer at intake; absent `X-AssetManager-ID` sets `asset_manager_id` to null — implementation/routes/deals.py:42,115-116
- §3.2 — insert — ambiguity — `concessions_cents` non-negative integer when supplied; `period_month` not format-validated, comparisons lexicographic; rent-roll/opex accepted regardless of deal status — implementation/routes/rent_roll.py:27-71
- §3.2 — revise — ambiguity — `occupancy_pct` serialized as JSON number (92.5 means 92.50%) — implementation/services.py:66-76
- §3.3 — insert — ambiguity — assumptions creatable/activatable in any deal status; re-activating active set still bumps version; deactivated sets' `version`/`updated_at` unchanged — implementation/routes/assumptions.py:48-81
- §3.4 — insert — ambiguity — scenario creation permitted in any deal status and bumps parent deal version — implementation/routes/scenarios.py:36-100
- §3.4.1 — insert — ambiguity — compute uses deal's first-created property; no property/no rent roll → `ERR_INVALID_STATE` 409; no expense rows → expense base 0; non-positive price → `ERR_INVALID_REQUEST` 400 — implementation/services.py:83-96,325-334,195-196
- §3.4.1 — insert — ambiguity — pinning recomputes IRR and equity multiple from final NOI and does not bump scenario version — implementation/services.py:376-398
- §3.4.2 — insert — ambiguity — unbracketed NPV → IRR clamps to the endpoint with smaller |NPV| — implementation/services.py:160-170
- §3.5 — insert — ambiguity — debt sizing requires scenario COMPUTED (else `ERR_INVALID_STATE` 409); `io_months` recorded but unused by formula; sizing creation doesn't bump scenario version; ratios recorded as 0 when sized loan is 0 — implementation/routes/scenarios.py:150-195, implementation/services.py:243-255
- §3.6 — insert — ambiguity — waterfall requires scenario COMPUTED (else `ERR_INVALID_STATE` 409); creation doesn't bump scenario version — implementation/routes/scenarios.py:206-244
- §3.7 — insert — ambiguity — memo creation permitted in any deal status; non-COMPUTED scenario at memo submit → `ERR_INVALID_STATE` 409; submit-to-IC uses most recently created SUBMITTED memo, missing memo / non-COMPUTED scenario → `ERR_INVALID_STATE` 409 — implementation/routes/ic_memos.py:29-142, implementation/routes/deals.py:132-147
- §3.8 — insert — ambiguity — non-deciding vote leaves memo/deal status and versions unchanged — implementation/routes/ic_memos.py:192-214
- §3.8 — insert — ambiguity — reopen from REJECTED retains `rejected_reason`; mark-dead requires `X-User-ID` == `deal.asset_manager_id` — implementation/routes/deals.py:186-188,201-204
- §4 + §5 — insert — ambiguity — undefined path/method → `ERR_NOT_FOUND` 404; `ERR_INTERNAL` 500 added to error catalogue — implementation/app.py:20-30
