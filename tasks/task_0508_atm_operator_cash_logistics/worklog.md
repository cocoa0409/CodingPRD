# Worklog — task_0508_atm_operator_cash_logistics

## Step 1: Create task directory — 2026-06-26T08:22:38.000Z

Created `tasks/task_0508_atm_operator_cash_logistics/` and `tasks/task_0508_atm_operator_cash_logistics/workspace/` (pre-allocated reserved index 0508; did not scan ./tasks).

## Step 2: Generate scaffold (Expert tier) — 2026-06-26T08:45:00.000Z

Generated a complete **Expert-tier** scaffold for **task_0508 — Independent ATM Operator & Cash Logistics** (Allpoint-network style), purely from the scenario + skill spec (no sibling tasks consulted). All three files pass `scaffold_lint.py` with `VERDICT: clean lint`, and every formula-derived assertion was executed in Python and pinned as a literal.

**Files written** (all under `tasks/task_0508_atm_operator_cash_logistics/`):
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Complexity profile:** primary archetype `ledger_reconciliation` + secondary `pricing_engine`; flat topology; parallel state-machine shape; peer-roles RBAC; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers, derived_field_reconciliation.

**Counts:**
- **Entities: 13** — Location, SiteMerchant, ArmoredRoute, Vault, ATM, Cassette, ReplenishmentOrder, Transaction (event), CashCount, ServiceTicket, SettlementRun, CommissionStatement, FeeDisclosure. 18 FKs, all reverse-reachable.
- **State machines: 7** — ATM (parallel: operational_status × cash_status), ReplenishmentOrder (branching + compensation), ServiceTicket (cyclic reopen loop), SettlementRun (linear), CommissionStatement (branching), FeeDisclosure (branching). 1 concurrency rule (OCC on Vault.version for dispatch).
- **Calculations: 5** — cash_load_forecast (forward vs chronological dual-variant), settlement_net_operator_revenue (tiered interchange + kind branch), commission_split (eval-order + greater_of/pct_only variants), cash_count_reconciliation, vault_cash_position (conservation invariant).
- **Endpoints: 52** (50 business + 2 test-driving: `/_clock/set_current_utc`, `/_inject/atm_monthly_wd_count`).
- **Error catalog: 21** codes.
- **Roles: 5** — PlatformAdmin, VaultController, FieldTech, SettlementOfficer, ComplianceOfficer.

**Test-index instance counts:**
- **§1.8: 18 instances** = 9 rule_ids × 2 each (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- **§1.9: 39 instances total** (33 active + 6 `excluded_because` stubs) across all 9 claim-extraction-guide sections. All 57 names unique across both files; all stub references resolve to named §1.8 instances.

**Key design points:** interchange tiers flip at monthly_seq >500 (boundary 500 vs 501); commission month-to-date ceiling keyed on statement `created_at` month; route windows half-open `[start,end)` while ATM lockout closed-interval + 30-min buffer; overlap/lockout candidate sets committed-only `{DISPATCHED, LOADED}`; vault conservation `balance + in_transit + in_machine == provisioned`.

## Step 3: Copy INSTRUCTION.md — 2026-06-26T08:47:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0508_atm_operator_cash_logistics/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-26T08:53:00.000Z

Generated the PRD at `workspace/PRD.md` for the **ATM Cash Logistics API** (ledger-reconciliation + pricing-engine domain). Did NOT open either design index file.

**Section structure:**
- **§1 Introduction** — 3 paragraphs framing the cash-conservation / revenue-integrity / compliance triad.
- **§2 Global Specifications** (9 subsections): RBAC (5 opaque roles + headers), response envelope, pagination, common resource properties (Transaction lacks `updated_at`/`version`), derived-field/parallel-state-dimension propagation, nested-retrieval + validation ordering (`ERR_INVALID_REQUEST`/`ERR_INVALID_STATE`), integer-cents precision + vault conservation invariant, OCC on vault dispatch, fee-disclosure gate.
- **§3 Business Logic** (12 subsections): network provisioning, ATM/cassette commissioning, dual-variant cash-load forecast, dispatch, window/lockout/sufficiency rules, load→withdraw→reconcile flow, recall compensation, service tickets (cyclic reopen + owner check), fee-disclosure compliance, settlement revenue computation, tiered commission split, logical clock + test seeders.
- **§4** 4-column endpoint table (53 endpoints). **§5** 2-column error table (21 errors).

**Coverage (all hard contracts PASS):** Contract 1 field names 71/71; Contract 2 rules all 14 entities + every transition + 5 calculations + OCC; Contract 3 §3 path purity 0 leaks; all 21 error IDs + 48 enum/state values present.

**Length:** ~7,200 words / 304 lines.

## Step 5: Generate unit tests — 2026-06-26T09:14:00.000Z

Generated complete test infrastructure under the design-index-only contract.

**Test files: 7** (plus `conftest.py`) in `test_suite/`: `test_01_provisioning_and_access.py`, `test_02_replenishment_and_vault.py`, `test_03_reconciliation_and_forecast.py`, `test_04_compliance_disclosures.py`, `test_05_settlement_and_commission.py`, `test_06_service_tickets.py`, `test_07_difficulty_complements.py`.

**Total tests: 68**
- **Queue A (Difficulty): 36 tests** covering all **18** difficulty instances, ≥2 tests each.
- **Queue B (Corner): 32 tests** covering **32 of 33** non-stub corner instances, ≥1 each.

**Instances skipped under PRD-first filter: 1** — `Corner/endpoints/list_orders_filtered_by_atm` (filter-by-`atm_id` semantics appear only in §4 routing table, no §3 prose — C2 rule-bearing-citation unmet). Left as documented gap. 6 `excluded_because:` corner stubs correctly not translated.

**test_helpers modules: 9** — `types.py`, `api_client.py` (52 endpoint methods), `api_errors.py` (21 errors), `assertions.py` (per-entity + vault-conservation invariant; Transaction append-only no `updated_at`/`version`), `factories.py`, `constants.py`, `test_users.py` (5 opaque roles + per-id FieldTech builders for ticket-ownership), `fixtures.py` (tiered composite setups), `__init__.py`.

**Audits passed:** every test carries exactly one verbatim `Design:` tag resolving to a real instance; all 101 PRD citations literally present (C1); no skip/xfail; no scaffold leakage; full package imports cleanly; pre-computed literals (forecast 1750000/1926000, interchange 196/77, commission 600/244/161/39/200, net 1631/261, variance −500/−501) verified against PRD math.

## Step 6: Generate implementation — 2026-06-26T09:14:00.000Z

Built complete Python + Flask implementation in `workspace/implementation/` (33 files).

**Files:** `start.sh`, `requirements.txt` (Flask 3.0.3 + waitress 3.0.0); entry/infra `app.py`, `db.py`, `clock.py`, `errors.py`, `response.py`, `middleware.py`, `serialize.py`, `validate.py`, `lookups.py`, `util.py`, `constants.py`; 8 route files; 10 service files.

**Endpoints: 52 implemented** (all PRD §4, incl. `/_clock/set_current_utc`, `/_inject/atm_monthly_wd_count`).

**State machines:** ATM parallel dimensions (`operational_status` × `cash_status`, independent; only cross-guard OUT_OF_SERVICE blocks confirm-load); ReplenishmentOrder branching-with-revert (SCHEDULED→DISPATCHED→LOADED→SETTLED or →RECALLED); ServiceTicket cyclic (reopen loop, IN_SERVICE restore only when no other OPEN/ACKNOWLEDGED remains; ownership on resolve); SettlementRun linear; CommissionStatement & FeeDisclosure branching. Validation precedence ladder (auth→role→existence→body→state→business).

**Calculations:** Vault conservation `balance = provisioned − in_transit(DISPATCHED) − in_machine(LOADED) − reconciled_out(SETTLED)` (SETTLED cash leaves permanently; recall restores). Forecast dual-variant (FORWARD fixed-divisor-14 half-open vs CHRONOLOGICAL since last load, fallback FORWARD; safety 5/4 integer; ceil-to-note). Settlement marginal interchange tiers by `monthly_seq` (35/42/50), 8¢ network fee (net=1631). Commission split (pct floor → basis → monthly ceiling on `created_at` month → SUSPENDED=0; GREATER_OF=600, ceiling-cap=39, void-frees-headroom=161). Cash-count variance/outcome inclusive tolerance + cassette charging.

**start.sh:** reads `$PORT` (default 10000), binds **0.0.0.0**, foreground via `exec python3 app.py`; pip install guarded; **in-memory only** (module dicts, no SQLite/disk) — kill+relaunch wipes state (~50ms boot); waitress with Flask-dev fallback.

## Step 7: Test & fix iteration loop — 2026-06-26T09:25:00.000Z

Final state: full 8-round parallel sweep passes **68/68 in every round**.

**Iterations run:** 2 sweeps to diagnose + confirm (the diagnostic sweep found 2 consistent failures across all 8 rounds; the confirmation sweep after fixes passed 68/68 in all 8 rounds).

**Tests deleted:** None. Both failures traced to genuine PRD-covered, uniquely-derivable rules — one a test-setup bug, one a real implementation bug plus a test-assertion mistranslation.

**Fixes applied to `test_suite/`** (assertion/setup mistranslations against verbatim PRD prose):
- `test_01_provisioning_and_access.py` → `test_list_atms_pagination_envelope`: setup bug. The test created 2 ATMs and asserted `total_count == 2`, but `provision_network()` already creates one ATM at the same `location_id`, so the location filter returned 3. Fixed the setup to provision the two paginated ATMs at a fresh dedicated location (reusing the network's merchant + route) so the `location_id` filter returns exactly the 2 the test created. Assertion unchanged; PRD §2.3 pagination contract preserved.
- `test_03_reconciliation_and_forecast.py` → `test_closeout_cascade_depth3_atm_order_vault` and `test_07_difficulty_complements.py` → `test_closeout_cascade_decrements_vault_in_machine`: both asserted post-closeout `balance_cents == 99_800_000`, which contradicts the verbatim PRD §2.7 formula `balance_cents = provisioned_cents − in_transit_cents − in_machine_cents` and the invariant "the sum … equals `provisioned_cents`" "at all times … conserved forever … two buckets in equal and opposite amounts." Corrected both to `== 100_000_000` (close-out empties `in_machine`, returning that cash to on-hand balance). This is exactly symmetric with the already-passing `test_vault_conservation_dispatch_then_recall` (recall restores balance to full provisioned).

**Fixes applied to `implementation/`:**
- `services/vault.py` → `position()`: removed the spurious `reconciled_out` term. The implementation computed `balance = provisioned − in_transit − in_machine − reconciled_out` (treating SETTLED orders as permanently destroying cash), which violated the verbatim §2.7 formula and broke the conservation invariant after every close-out. Now `balance = provisioned − in_transit − in_machine`, with SETTLED orders contributing to no bucket (identical to RECALLED), so `balance + in_transit + in_machine == provisioned` holds at all times. This matches both the PRD §2.7 prose and the SCAFFOLD design (`balance_cents := provisioned_cents − in_transit_cents − in_machine_cents`; close-out side effect is only `in_machine_cents −= order_amount_cents`).

**Note on the §3.6 "reconciled out of vault custody entirely" phrase:** the prior implementer read this as cash leaving the system permanently. §2.7's explicit formula and "conserved forever / two buckets equal-and-opposite" language uniquely override that reading — the phrase describes the cash exiting *machine* custody (the `in_machine` bucket) and returning to on-hand `balance`, not being destroyed.

## Step 8: Finalize PRD — 2026-06-26T09:32:00.000Z

Produced `workspace/PRD_FINALIZED.md` (304 lines, ~0% line delta — one line revised in place).

**Change (one bullet):**
- **§3.6 (close-out / cash conservation)** — *revise* — replaced the misleading clause "the cash … is now reconciled out of vault custody entirely" (which misled the prior implementer into a `reconciled_out` fourth term that destroyed cash) with prose pinning that close-out moves cash from `in_machine_cents` back to on-hand `balance_cents`, conserving `provisioned_cents` per §2.7, and that a `SETTLED` order (like `RECALLED`) funds no bucket — `implementation/services/vault.py:35` + `services/reconciliation.py:48-71`.

**Step 7 diff items mapped:** test_01 pagination = pure fixture bug (no PRD edit); test_03/test_07 balance assertions = mistranslations vs already-verbatim §2.7 (no PRD edit); vault.py `position()` fix = the one alignment surface → the single §3.6 edit.

**Per-edit pre-edit search:** enumerated `vault.py::position()`, `reconciliation.py::close_out()`, `replenishment.py` (dispatch/confirm_load/recall), `serialize.py:38-41`, `db.py:61-65`, plus full grep of `SETTLED|RECALLED|in_machine|in_transit|provisioned` across `services/`+`routes/` — confirmed no path lets a SETTLED order fund a bucket or destroy cash. Wording scoped to cash buckets only; made NO claim about vault `version` on close-out (subagent flagged that `reconciliation.py:67` calls `store.touch(vault)` which DOES bump version, possibly contradicting §2.8 "only dispatch/recall increment version" — left to Step 9 as off-scope for Step 8).

## Step 9: Complete PRD scan — 2026-06-26T09:40:00.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md` (full PRD-vs-implementation scan).

**Counts:** source `PRD_FINALIZED.md` 304 lines / 49,926 chars → `PRD_COMPLETED.md` 304 lines / 51,554 chars (char-delta **+1,628**; line count unchanged — all in-paragraph). **6 changes: 5 ambiguity-pins, 1 mismatch-revision.**

**Per-change:**
- §2.8 — revise — mismatch — added reconciliation close-out to the operations that advance vault `version`; pinned exactly three paths bump it (dispatch, recall-of-DISPATCHED, close-out), confirm-load does not — `services/reconciliation.py:67`, `services/replenishment.py:113,175`.
- §3.6 — insert — ambiguity — close-out increments vault `version` by one — `services/reconciliation.py:67`.
- §3.6 — insert — ambiguity — close-out resets machine `dispensed_cents_since_load` to zero — `services/reconciliation.py:56`.
- §3.9 — insert — ambiguity — disclosure-approve multi-failure precedence: cap → ack → mismatch — `services/disclosure.py:15-26`.
- §3.4 — insert — ambiguity — order serialization carries `expected_vault_version` (null while SCHEDULED, set to OCC token on dispatch) — `serialize.py:109`, `services/replenishment.py:102`.
- §3.3 — insert — ambiguity — forecast response `basis` echoes requested variant (CHRONOLOGICAL stays CHRONOLOGICAL even on never-loaded fallback; FORWARD when omitted) — `services/forecast.py:64-80`, `routes/atms.py:88`.
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` clamped to bounds; non-integer raises `ERR_INVALID_REQUEST` — `validate.py:85-110`.

**Step-8 lead confirmed:** close-out DOES bump vault `version`; exhaustive scan confirms `version` increments in exactly three places (dispatch, recall-of-DISPATCHED, close-out); confirm-load does not. §2.8 + §3.6 reconciled.

**Intentionally left unspecified:** default (no-`cassette_allocations`) multi-cassette load distribution — genuinely unobservable (tests use single-cassette setups), pinning it would over-specify.

---

## Pipeline complete — 2026-06-26T09:40:00.000Z

All 9 steps done. Final 8-round parallel stability sweep: **68/68 passing in every round.** Deliverables present: SCAFFOLD.yaml + 2 design indices, test_helpers/ (9 modules), test_suite/ (7 files, 68 tests), workspace/implementation/ (33 files, in-memory Flask, start.sh), workspace/{PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md}.
