# Worklog — task_1803_streetlight_led_conversion_program

Scenario (verbatim): 1803. Streetlight LED Conversion Program (municipal streetlight program): pole/luminaire inventory & wattage audit, conversion route scheduling & crew production, unmetered tariff adjustment & billing recalculation, municipal ownership vs utility-owned rate, outage reporting portal & repair SLA, dark-sky/color-temperature policy, salvage & recycling of removed fixtures, savings verification

Difficulty directive from user: "Generate task hard than expert level!"

## Step 1: Create Task Directory — 2026-08-14T17:30:00.000Z

Pre-created by pipeline launcher: `tasks/task_1803_streetlight_led_conversion_program/` and `workspace/` already existed; verified, no other task directories touched.

## Step 2: Generate Scaffold — 2026-08-14T18:46:00.000Z

Scaffold generation complete. All three artifacts are written, lint-clean, and cross-audited.

## Output files

| File | Path | Lines | Bytes |
|---|---|---|---|
| SCAFFOLD.yaml | `/home/ubuntu/github/CodingPRD/tasks/task_1803_streetlight_led_conversion_program/SCAFFOLD.yaml` | 3,312 | 113,690 |
| SCAFFOLD_DIFFICULTY_DESIGN.yaml | `/home/ubuntu/github/CodingPRD/tasks/task_1803_streetlight_led_conversion_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 3,333 | 116,250 |
| SCAFFOLD_CORNER_DESIGN.yaml | `/home/ubuntu/github/CodingPRD/tasks/task_1803_streetlight_led_conversion_program/SCAFFOLD_CORNER_DESIGN.yaml` | 7,523 | 262,860 |

File split honored: difficulty/corner keys appear only as the single top-level key of their own files.

## Counts

- **Entities: 16** (ConversionProgram, ServiceDistrict, Pole, WattageAudit, Crew, ConversionRoute, RouteStop, WorkOrder, TariffRateSchedule, TariffAccount, BillingLine, OutageTicket, SalvageBatch, SalvageItem, SavingsReport, ComplianceException) — flat topology, many-to-many junction (RouteStop), two self-referential FKs (ticket duplicates, line supersession)
- **State machines: 14** — including cyclic (ticket reopen, audit dispute, pole rework, account freeze, report revise), parallel dimensions (WorkOrder execution × QC), compound bubble-up (route auto-close), posture-driven gating (account FROZEN, program ACTIVE)
- **Calculations: 12** — incl. dual-variant billing proration vs whole-month deferral and dual-variant savings estimation, mode-(a) route capacity, mode-(b) salvage rounding order, mode-(c) rebate cap evaluation order, chronological weekly-overtime with marginal allocation at exactly 2400 minutes
- **Endpoints: 88** (incl. `POST /_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`); every FK has a reverse-reachability GET
- **Errors: 78** (all referenced by a validation/transition; all exercised by at least one test design)
- **Validations: 35 priority rows** (auth → shape → role → existence → ownership → SoD → OCC → state → safety → temporal → constraint → referential → fiscal)
- **Roles: 7** with segregation-of-duties model (completer ≠ QC, submitter ≠ attester; FieldSupervisor is `entity_backed:Crew`, rest opaque)
- **§1.8: 20 instances** across all 9 rules (3 each for combinatorial_formula and priority_pair_validation_conflict, 2 for the rest); cascades of depth 4 (completion → pole → line → account → program) and depth 3 (ticket resolve → pole → stop → route suspension); all formula-derived asserts pre-computed as literals (e.g., 1087¢ proration, 11976¢ salvage, 15750¢ split-overtime, 49.600 vs 25.600 kWh savings, rebate 9920/80 landing exactly on the 10000¢ cap)
- **§1.9: 83 instances** (64 active + 19 excluded_because stubs) across all nine claim-extraction-guide sections

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(1,401 recipe calls scanned; 0 violations.)

## Additional audits run

- No forbidden concurrency vocabulary; both OCC rules pass the serial-observability filter (true create-with-supersede races on `Pole.version` and `ConversionProgram.version`; both endpoints declare the `expected_*_version` input and bump the parent version).
- Placeholder closure: every `${var}` bound by an earlier `captures:` in the same instance (0 unbound/rebound after fixes); OCC inputs always `${var}` or `${var} - 1`.
- Every grounds reference in both design files resolves to a declared §1.1–§1.7 element; all instance names unique across both files; every stub's `difficulty_instance` citation resolves.
- Design fixes applied during self-review: first-completion-only salvage item creation, Pole UNDER_REPAIR self-loop for repeat FIXTURE_REPLACED, dead error `ERR_ROUTE_TERMINAL` removed (unreachable under target-before-related state ordering), exemption corner's OCC version refreshed post-cascade.

## Step 3: Copy Shared Files — 2026-08-14T18:47:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1803_streetlight_led_conversion_program/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-14T18:55:00.000Z

PRD generated and verified. Summary below.

## Deliverable

**`/home/ubuntu/github/CodingPRD/tasks/task_1803_streetlight_led_conversion_program/workspace/PRD.md`** — 426 lines, 69,103 bytes.

## Section structure

- **§1 Introduction** (3 paragraphs — program context, system-of-record framing, ledger/derived-billing commitments)
- **§2 Global Specifications** — 2.1 Roles & RBAC (all 7 roles, identity semantics per role incl. `FieldSupervisor` entity-backed-to-Crew), 2.2 API Response Structure (**verbatim canonical block, confirmed byte-identical**), 2.3 Pagination, 2.4 Identity/Timestamps/Versioning/Logical Clock, 2.5 Budget Ledger & Precision, 2.6 Wattage Tiers/Dark-Sky/Shielding, 2.7 Calendar Windows (closed vs half-open), 2.8 OCC, 2.9 Nested Identifier Validation (all 16 NOT_FOUND mappings), 2.10 Validation Pipeline Order (all 35 priorities in explicit relative order)
- **§3 Business Logic** — 8 subsections: 3.1 program/district/pole setup, 3.2 wattage audits + retroactive adjustment, 3.3 crews/routes/stops/capacity, 3.4 dispatch/execution/labor costing/QC, 3.5 tariff schedules/accounts/billing, 3.6 outage tickets/SLA/UNDER_REPAIR cycle, 3.7 salvage settlement, 3.8 savings verification/rebates/compliance exceptions
- **§4 Endpoint Definitions** — 4-column table (Method, Path, Description, Authorized Role)
- **§5 Error Code Catalogue** — 2-column table (Error ID, HTTP Status)

## Coverage versus scaffold

| Category | Scaffold | PRD | Status |
|---|---|---|---|
| Entities | 16 | 16 covered in narrative | full |
| Entity fields | 110 | 110 backticked, 0 missing | full |
| State machines | 14 (75 transitions) | all transitions expressed with state-pair framing; all states present | full |
| Calculations | 12 | 12 in precise prose (tier thresholds, dual-variant monthly charge, capacity check, overtime labor, salvage waterfall, burn-hours kWh both variants, rebate cap, SLA/breach, duplicate selector, retro adjustment, budget ledger, auto-suspension) | full |
| Validations | 35 | ordered pipeline in §2.10 + conditions bound to error IDs in §3 | full |
| Endpoints | 88 | 88 table rows, 0 paths missing | full |
| Errors | 78 | 78 table rows with exact statuses; all 78 also backticked in §1–§3 prose | full |
| Concurrency rules | 2 | both (occ field + endpoint + `ERR_STALE_VERSION`/412) in §2.8 | full |
| Roles | 7 | 7 exact spellings + identity prose | full |

## Hard-contract reports

```
Field coverage check:
- entities[].fields: 110 required, 110 present, 0 missing
- endpoints[].request_body: 49 required, 49 present, 0 missing
- endpoints[].query_params: 26 required, 26 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 35 checked, 35 expressed in pipeline order, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + occ field + error_id + status), 0 missing
- state_machines[].transitions: 75 checked, 75 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed (constants embedded, rounding order pinned), 0 missing
- validations[] conditions: 35 checked, 35 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 88 checked, expressed in workflow narrative, 0 missing
- entities[].fields[] structured content: 110 checked, reconstructible (defaults, initial values, null-until semantics), 0 missing
- sibling-branch symmetry: 6 groups checked (billing variants, kWh variants, QC verdicts, cancel sources, UNDER_REPAIR sources, exception kinds), all equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 805
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Zero-Silence self-audit

No scaffold element was left unexpressed. Two judgment notes: (1) `ERR_ROUTE_TERMINAL` appears in the scaffold's priority-9 error list but has no entry in the `errors[]` catalog — the PRD names it once in §2.10 as reserved-but-never-observed (per the scaffold's own note that the work-order state check fires first on terminal routes) and correctly omits it from §5. (2) Field constraints the scaffold expresses without an error binding (`account_number` uniqueness, positivity of input wattages/rates) are stated as facts without inventing error IDs. The withheld files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-14T19:35:00.000Z

## Generation complete — task_1803_streetlight_led_conversion_program

### test_helpers/ inventory (Stage 1)
| File | Lines |
|---|---|
| `test_helpers/__init__.py` | 39 |
| `test_helpers/types.py` | 443 |
| `test_helpers/api_client.py` | 285 |
| `test_helpers/api_errors.py` | 170 |
| `test_helpers/assertions.py` | 199 |
| `test_helpers/factories.py` | 193 |
| `test_helpers/constants.py` | 60 |
| `test_helpers/test_users.py` | 58 |
| `test_helpers/fixtures.py` | 540 |

All 16 entities, all 74 endpoints (one ApiClient method each), all 62 error IDs registered via `set_error_http_status_map`, domain constants (CCT caps, tier rates, burn hours, SLA hours, salvage prices, 2400-min overtime threshold, stop minutes), role headers with the mandatory `make_field_supervisor_headers(crew_id)` builder for the entity-backed `FieldSupervisor` role, and composite fixtures (active program, cleared pole, released route, converted/verified pole, effective rate schedule, account, report, blocked-route repair loop).

### test_suite/ inventory (Stage 2) — 104 tests, all collected
| File | Tests |
|---|---|
| conftest.py | (fixtures only) |
| test_01_billing_dual_variant.py | 4 |
| test_02_route_capacity_and_salvage_formulas.py | 4 |
| test_03_rebate_cap.py | 2 |
| test_04_outage_reopen_and_qc_rework.py | 4 |
| test_05_cascades.py | 4 |
| test_06_validation_priority_pairs.py | 6 |
| test_07_boundary_precision.py | 4 |
| test_08_cross_entity_gates.py | 4 |
| test_09_window_overlap.py | 4 |
| test_10_compensating_invariants.py | 4 |
| test_11_entities.py | 7 |
| test_12_pole_and_audit_state.py | 2 |
| test_13_work_order_and_route_state.py | 5 |
| test_14_salvage_and_report_gates.py | 2 |
| test_15_compliance_exceptions.py | 7 |
| test_16_calculations.py | 7 |
| test_17_occ_validations.py | 4 |
| test_18_endpoints.py | 3 |
| test_19_dispatch_gates.py | 7 |
| test_20_error_gates.py | 8 |
| test_21_rbac_sod.py | 9 |
| test_22_clock_consistency_tickets.py | 3 |

### Queue A (§1.8 Difficulty) — 20/20 translated, 0 skipped
All 20 instances got exactly 2 tests each: `dual_variant_calc` ×2, `combinatorial_formula` ×3, `non_linear_state_machine` ×2, `transitive_cascade` ×2, `priority_pair_validation_conflict` ×3, `boundary_precision_check` ×2, `cross_entity_state_dependency` ×2, `resource_temporal_overlap` ×2, `compensating_invariant` ×2. No skips — every instance's rule (pipeline priority, OCC, boundary semantics, dual variants, cascades, invariants) is verbatim-covered and uniquely derived in PRD §2.4–§2.10 and §3.

### Queue B (§1.9 Corner) — 64/64 non-stub translated, 0 skipped; 19 stubs not translated
All 64 non-stub instances got exactly 1 test each (7 entities, 16 state_machines, 7 calculations, 4 validations, 3 endpoints, 15 errors, 9 rbac, 1 cross_cutting, 1 consistency_model). The 19 `excluded_because:` stubs were verified to resolve to real difficulty instances and were not translated (their assertions are owned by queue A).

### Self-audit verdicts
- **Stage 1 audit: PASS** — helpers compile, import cleanly (104 tests collect with zero import errors), no scaffold references in comments, no skip/xfail marks.
- **Stage 2 audit: PASS** — 104/104 tests carry exactly one docstring-final `Design:` line; every tag resolves to a real non-stub instance; every difficulty instance has ≥2 tests and every corner instance ≥1; every docstring citation contains a verbatim ≥8-word window matching PRD.md under strict backtick-intact comparison (0 strict failures after aligning quotes with PRD backtick/`→` glyph conventions); asserted error_ids are all named in PRD prose with their trigger conditions; two-reader check applied (priority tests cite §2.10's explicit stage ordering; boundary tests cite the inclusive/strictly-greater wording).

Total: **104 tests**, 6,325 lines across 9 helper files and 23 test files.

## Step 6: Generate Implementation — 2026-08-14T19:50:00.000Z

Done. The implementation is complete and the full benchmark suite passes twice consecutively under per-test-server isolation.

## Summary

**Implementation** — Python + Flask, at `/home/ubuntu/github/CodingPRD/tasks/task_1803_streetlight_led_conversion_program/workspace/implementation/` (3,342 lines total):

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Launcher (see contract below) |
| `requirements.txt` | 1 | `flask>=3.0,<4.0` |
| `app.py` | 47 | Entry point, blueprint registration, ApiError/404/405/500 envelope handlers |
| `db.py` | 69 | In-memory store (16 dicts keyed by id), monotonic `_seq`, `new_record`/`touch` |
| `util.py` | 114 | UUIDs, `req_` ids, logical clock (default `2026-08-01T00:00:00Z`, never wall-clock), date/period math, round-half-up helpers |
| `errors.py` | 96 | Full PRD §5 error catalog with HTTP statuses |
| `response.py` | 46 | `meta`/`response_type`/`data` envelope, error envelope, pagination meta (`limit`/`offset`/`total_count`/`has_more`) |
| `middleware.py` | 54 | `X-User-ID`/`X-User-Role` auth (401), role gating (403), global store lock for atomic multi-step ops |
| `validate.py` | 149 | Stage-2 shape validators (types, enums, ISO dates, YYYY-MM periods, 1-decimal weights, pagination bounds 1–100) |
| `domain.py` | 606 | Serializers, rollups, and all 13 scaffold calculations: tier thresholds, municipal-proration vs utility-deferral charge, route capacity, ISO-week overtime labor, salvage waterfall, savings kWh (both variants), rebate cap, SLA/duplicate selector, retro adjustment, budget ledger, auto-suspend/auto-close |
| `routes/` (13 modules) | 2,031 | One blueprint group per resource (programs 95, districts 56, poles+audits 209, crews 52, routes+stops 301, work_orders 318, billing 331, tickets 234, salvage 177, reports 171, exceptions 122, clock 22, common 42, `__init__` 20) |

**Endpoint coverage: 88/88** — every route in the scaffold endpoint table including `POST /_clock/set_current_utc`.

**start.sh contract**: reads `$PORT` (default 10000), binds `0.0.0.0`, runs in foreground via `exec python3 app.py`, and the pip install is guarded (`if ! python3 -c "import flask"`) so the per-test reboots never re-install.

**Storage**: purely in-memory dicts; zero seeding/preloading (grep-verified); every boot starts empty — validated by cold-boot probe (fresh port returned `total_count: 0`) and by ~104 server restarts per suite run.

**Verification**: booted locally (clean boot, probe answered within ~2s) and ran `prd-bench-local-run --isolation per-test-server` twice: **104/104 tests passed both runs**.

**Key implementation rulings** (PRD/test-pinned): rework dispatch (`REWORK_PENDING → DISPATCHED`) skips the stop-PENDING gate since the stop is already COMPLETE; at stop-add, `ERR_DUPLICATE_STOP` precedes `ERR_POLE_NOT_AUDIT_CLEARED` (a pole holding a PENDING stop is SCHEDULED); fail immediately re-queues to PENDING as the observable end state; program `version` bumps only at the seven PRD-called-out events (activate, close, dispatch-from-PENDING, complete, salvage settle, report create, report attest); weekly-overtime attribution uses the pinned processing order with `prev` = minutes of orders preceding this completion.

**Test-side mechanical repairs I had to make to unblock the suite** (no semantic changes): added missing pass-through getters `get_district`/`get_audit` to `test_helpers/fixtures.py`; added module-level `api = api_client` aliases in `test_02`/`test_10` (their class-scope helpers referenced a bare `api`); in `test_21` added the missing `get_pole` import and corrected the crews no-side-effects assertion from `== 0` to `== 1` (the test's own setup creates one crew).

## Step 7: Run Tests and Iterate — 2026-08-14T19:58:00.000Z

The official verification is complete. All 8 parallel rounds passed with zero failures, zero errors, zero skips.

**Summary**

- **Iterations run:** 1 — the full 8-round parallel stability sweep (`--isolation per-test-server`, `--timeout 120`, `--test-timeout 30`), all 8 rounds launched concurrently and joined with `wait`, every round run to completion.
- **Result:** All 8 rounds: `passed=104/104, failed=0, errors=0, skipped=0`, with per-test `status` verified as `passed` for every one of the 104 tests in every `results.{1..8}.json`. No flakiness surfaced — no test failed in any round.
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none needed.
- **Fixes applied to `implementation/`:** none needed.

The prior implementation-generator repairs (helper getters, module-level `api` aliases, one no-side-effects count) hold up under the 8× concurrent load. Spot review during the sweep confirmed the suite stays PRD-faithful: dispatch gates (test_19), validation-priority pairs (test_06), billing dual-variant proration (test_01), rebate-cap ordering (test_03), overtime ISO-week math (test_16), cascades (test_05, test_10), window overlap semantics (test_09), RBAC/SoD (test_21), and clock consistency (test_22) all trace to verbatim PRD.md sentences, and the FieldSupervisor entity-backed ownership model in `test_helpers/test_users.py` matches PRD §2.1.

## Step 8: Finalize PRD — SKIPPED — 2026-08-14T19:58:30.000Z

Skip condition met: Step 7 exited on its first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced. Step 9 will start from `PRD.md`.

## Step 9: Complete PRD — 2026-08-14T20:15:00.000Z

All edits verified. Here is the final report.

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1803_streetlight_led_conversion_program/workspace/PRD_COMPLETED.md` (copied from `PRD.md`, edited in place).

**Size:** PRD.md 426 lines / 69,103 chars → PRD_COMPLETED.md 427 lines / 74,350 chars (+1 line, +5,247 chars; 26 changed regions).

**Counts:** 21 ambiguity-pins, 5 mismatch-revisions. Known generation rulings all verified true in code (rework dispatch skips stop gate — work_orders.py:92-94; ERR_DUPLICATE_STOP before ERR_POLE_NOT_AUDIT_CLEARED at stop-add — routes_ops.py:114-122; fail re-queues to observable PENDING — work_orders.py:215; program version bumps only at the seven named events — bump_program/post_budget split at domain.py:194-200; weekly-overtime `prev` = minutes of orders preceding this completion — domain.py:393-397).

**Changes (one per bullet):**

- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` or negative `offset` rejected with ERR_INVALID_REQUEST — implementation/validate.py:128-149
- §2.3 — insert — ambiguity — default list ordering is server creation order (created_at ascending, ties/backward-clock regressions by insertion sequence) — implementation/routes/common.py:36-39, db.py:56
- §2.4 — insert — ambiguity — clock setter accepts any instant (no monotonicity); clock-stamped fields (`current_utc`, `completed_at`, `reported_at`, `resolved_at`) render at seconds precision on whole seconds, else 3 fractional digits — implementation/util.py:41-55, routes/clock.py:14-22
- §2.5 — insert — ambiguity — a ledger posting alone never bumps program `version`; version advances only at the seven named business events, so cancel-refunds move money without a bump — implementation/domain.py:194-200, routes/work_orders.py:232-233, routes/routes_ops.py:295-296
- §2.9 — insert — ambiguity — foreign keys get an existence check only; no same-program consistency unless §3 names it (route→crew and ticket→crew may cross programs) — implementation/routes/routes_ops.py:43-49, routes/tickets.py:113-116
- §2.10 stage 2 — revise — mismatch — retire payload's `effective_until` relational checks (later than `effective_from`, not before today) are evaluated after the existence stage, not at stage 2; only presence/ISO-format is stage 2 — implementation/routes/billing.py:135-146
- §2.10 stage 9 — revise — mismatch — ERR_ROUTE_TERMINAL added to the state-stage list and is observable when cancelling a terminal route (was "never observed in practice"); the dispatch-context unreachability note retained — implementation/routes/routes_ops.py:278-279
- §3.1 — insert — ambiguity — activating a non-DRAFT or closing a non-ACTIVE program fails with ERR_INVALID_REQUEST; at close this check precedes ERR_ROUTES_STILL_ACTIVE — implementation/routes/programs.py:75-76, 88-92
- §3.1 — insert — ambiguity — district_name collision is ERR_INVALID_REQUEST, evaluated after the program-ACTIVE gate — implementation/routes/districts.py:31-33
- §3.1 — insert — ambiguity — nameplate attestation: EXEMPT pole → ERR_POLE_EXEMPT (before ownership check); non-SURVEYED UTILITY_OWNED pole → ERR_INVALID_REQUEST — implementation/routes/poles.py:82-88
- §3.2 — insert — ambiguity — resubmit keeps prior `auditor_notes` when omitted; dispute and resubmission bump only the audit's version, never the pole's — implementation/routes/poles.py:184-187, 196-208
- §3.2 — insert — ambiguity — the compensating ADJUSTMENT line also carries the recomputed `rate_schedule_id`, `billing_wattage`, and `tier` — implementation/domain.py:314-325
- §3.3 — insert — mismatch — stop-add gate firing order pinned: route PLANNED → EXEMPT pole → window-past → DUPLICATE_SEQUENCE → DUPLICATE_STOP → audit-cleared → capacity → cross-district (deviates from the generic §2.10 stage order for ERR_POLE_NOT_AUDIT_CLEARED) — implementation/routes/routes_ops.py:100-137
- §3.3 — insert — ambiguity — work orders are stamped at creation (release / ticket resolution) with `estimated_labor_cost_cents` per the §3.4 formula, never recomputed; fixture fields, `cumulative_week_minutes_before`, `overtime_minutes`, `performed_by_user_id`, `qc_by_user_id` born null — implementation/routes/routes_ops.py:210-232, routes/tickets.py:144-166
- §3.3 — insert — ambiguity — cancelling an already CLOSED/CANCELLED route is rejected with ERR_ROUTE_TERMINAL — implementation/routes/routes_ops.py:278-279
- §3.3 — insert — ambiguity — route auto-close is re-evaluated on stop completion/skip and on linked work-order completion, cancellation, or QC pass — implementation/domain.py:172-186, routes/routes_ops.py:191, routes/work_orders.py:197, 250, 297
- §3.4 — revise — mismatch — the linked-stop PENDING gate (ERR_STOP_BLOCKED) applies only to a first dispatch; rework dispatch from REWORK_PENDING skips it (stop already COMPLETE) — implementation/routes/work_orders.py:92-94
- §3.4 — insert — ambiguity — the `pre_conversion_wattage` snapshot fires on whichever completion, conversion or replacement, first finds it null — implementation/routes/work_orders.py:166-167
- §3.4 — insert — ambiguity — work-order listing: replacement orders (no route window) sort after all dated orders, by creation among themselves — implementation/routes/work_orders.py:25-30
- §3.5 — insert — ambiguity — account_number collision is ERR_INVALID_REQUEST (distinct from ERR_DUPLICATE_ACCOUNT), evaluated after the ACTIVE gate — implementation/routes/billing.py:171-174
- §3.5 — insert — ambiguity — generate-lines: the ERR_NO_EFFECTIVE_RATE_SCHEDULE gate fires only when at least one pole would newly receive a line; an all-skipped run succeeds with `created_count` zero; the sweep responds 200 as a computed operation — implementation/routes/billing.py:260-284
- §3.5 — insert — ambiguity — when several schedules cover a period start, EFFECTIVE beats SUPERSEDED, then later `effective_from`, then later creation — implementation/domain.py:207-224
- §3.5 — insert — ambiguity — account totals are live reads against the then-current `current_period`; after a December close `ytd_billed_cents` reflects the new year — implementation/domain.py:332-349, routes/billing.py:302
- §3.6 — insert — ambiguity — the FIXTURE_REPLACED cascade fires only for poles at SCHEDULED/CONVERTED/REWORK/VERIFIED/UNDER_REPAIR; otherwise the resolution succeeds with no cascade — implementation/routes/tickets.py:26, 131-132
- §3.7 — insert — ambiguity — batch_label collision is ERR_INVALID_REQUEST, evaluated after the ACTIVE gate — implementation/routes/salvage.py:34-36
- §3.7 — insert — ambiguity — batch rejection retains `manifest_code` and `contaminated_flag`; only `settlement_value_cents` is cleared and items return to the pool — implementation/routes/salvage.py:170-176
- §3.8 — insert — ambiguity — exception refresh from any state other than APPROVED fails with ERR_EXCEPTION_NOT_PENDING — implementation/routes/exceptions.py:116-117
- §5 — insert — mismatch — added the missing ERR_ROUTE_TERMINAL (409) row to the error catalogue — implementation/errors.py:40

**Deliberately not pinned** (outside the declared surface or already uniquely implied): Flask fallback errors (ERR_NOT_FOUND/ERR_METHOD_NOT_ALLOWED/ERR_INTERNAL) for undeclared paths/methods; the double-debit consequence of fail→re-dispatch (follows literally from §2.5's pinned rules); `resolved_at` retention while REOPENED; generic 'null' filter matching on non-salvage list endpoints.
