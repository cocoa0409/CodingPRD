# Worklog — task_2465_water_utility_high_bill_investigation_leak_adjustment

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2465_water_utility_high_bill_investigation_leak_adjustment/` and its `workspace/` subdirectory. Index was pre-assigned by the invoking pipeline (2465); no scan of ./tasks/ was performed, no other task directory created.

## Step 2: Generate scaffold artifacts — 2026-09-02T00:00:00.000Z

Wrote `SCAFFOLD.yaml` (§1.0–§1.7: 13 entities, 9 state machines, 2 OCC rules, 12 calculations,
46 ordered validations, 65 endpoints, 57 errors, 6 roles), `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
(§1.8: 9 rules / 24 instances) and `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9: 9 sections / 83 instances,
54 with test recipes and 29 `excluded_because` stubs). `scaffold_lint.py` reports
`VERDICT: clean lint`. Generated from the supplied scenario text and the skill spec only; no
sibling task directory was read.

(The block above was written by the Step 2 subagent itself. Orchestrator-recorded verbatim
subagent return summary follows.)

All three scaffold artifacts are complete and lint-clean.

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_2465_water_utility_high_bill_investigation_leak_adjustment/`

**SCAFFOLD.yaml** (§1.0–§1.7, 3277 lines) — `api_prefix: ""`, profile `expert_plus` / `workflow_orchestration` + `pricing_engine`, layers dual_variant_calculation, rate_threshold_triggers, cascading_side_effects, optimistic_concurrency, derived_field_reconciliation; topology flat, machine shape cyclic, role_model segregation_of_duties, consistency immediate.
- **13 entities:** RateSchedule, BillingPeriod, ServiceAccount, Meter, MeterReading, Bill, HighBillInvestigation, MeterTestRequest, RepairProof, LeakAdjustment, PaymentArrangement, BoardAppeal, AccountLedgerEntry
- **9 state machines** (incl. the two-dimensional ServiceAccount `service_status`/`credit_status` pair and the cyclic investigation evidence/remand loop), **2 OCC rules** (`POST /leak-adjustments` on investigation version, `POST /payment-arrangements` on account version), **12 calculations**, **46 ordered validations**, **65 endpoints**, **57 error codes**, **6 roles** (Customer, CustomerServiceRep, MeterTechnician, BillingSupervisor, UtilityBoardClerk, SystemAdmin)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8) — all 9 §0.5 rules, **24 instances**: dual_variant 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 3.

**SCAFFOLD_CORNER_DESIGN.yaml** (§1.9) — all 9 claim-extraction-guide sections, **83 instances** (54 with full `test_recipe`, 29 `excluded_because` stubs pointing at named §1.8 instances): entities 12, state_machines 17, calculations 14, validations 9, endpoints 5, errors 17, rbac 3, cross_cutting_layers 5, consistency_model 1.

**Verification:**
- `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1511 calls scanned across 78 recipe-bearing instances)
- All 107 instance names unique across both design files; every stub cites an existing §1.8 instance and carries no `test_recipe`; no forbidden concurrency vocabulary remains (two benign phrasings — "wall-clock time" and "at the same time" — were reworded); `SCAFFOLD.yaml` carries neither design key.
- Two lint fixes this pass: the `GET /bills/{id}/adjustment-preview` corner calls passed `assumed_leak_type` in the query string instead of `payload:`, tripping check (c); aligned them to the payload form used in §1.8.
- Hard constraint honored: no sibling `task_*/` directory was listed, read, or grepped.

## Step 3: Copy shared files — 2026-09-02T23:22:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes). Verified all three scaffold artifacts present (3277 / 3141 / 4865 lines).

## Step 4: Generate PRD — 2026-09-02T23:37:00.000Z

PRD generated and verified at `/home/ubuntu/github/CodingPRD/tasks/task_2465_water_utility_high_bill_investigation_leak_adjustment/workspace/PRD.md`.

**Size:** 430 lines (431 including the trailing newline), written in three appends (§1–§2, §3, §4–§5).

**Sections covered (5 top-level, 20 subsections):**
- `## 1. Introduction` — three paragraphs; append-only ledger and segregation-of-duties commitments; notes the flat, prefix-less collection layout.
- `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC (all 6 roles, `Customer` as entity-backed `ServiceAccount`, other five opaque, per-role capability and prohibition narrative, the two user-identifier comparisons); 2.2 verbatim response-structure block (byte-identical to `section-2.2-response-structure.md`, confirmed programmatically); 2.3 pagination + the two domain orderings; 2.4 identifiers, timestamps, `version`, the `AccountLedgerEntry` exception, logical clock; 2.5 integer money/volume and rounding discipline; 2.6 both optimistic-concurrency rules; 2.7 the full 13-tier rejection ladder; 2.8 resolution order; 2.9 the ledger and derived account state; 2.10 billing-period lifecycle gates; 2.11 list filters.
- `## 3. Business Logic & Workflows` — 9 subsections: rate schedules/metering estate/register; bill generation and issue; investigation and the bounded evidence loop; meter accuracy testing and the FAST correction cascade; rebilling; determination and the six-step credit formula; approval/posting/reversal; collections (3.8, matching the §2.9 forward reference); board appeals.
- `## 4. Endpoint Definitions` — status-code paragraph plus a 4-column table.
- `## 5. Error Code Catalogue` — 2-column table; document ends here with no footer.

**Completeness (all verified by script against SCAFFOLD.yaml):** 13 entities, 9 state machines / 60 transitions (every atomic state name present in backticks; the only unmatched strings were compound `A | B | C` expressions, not real state names), 12 calculations (all named formulas rendered as prose), 46 validations (every error id paired to its condition), 65 endpoints (method+path set matches exactly — 0 missing, 0 extra), 57 error codes (57 rows), 6 roles.

**Contract reports:**
- **Contract 1 — Field-Name Coverage: PASS.** 142/142 required identifiers (entity fields ∪ endpoint inputs, optional `?` markers stripped) appear inside backticks; the 7 adjustment-preview/clock response identifiers (`recommended_variant`, `excess_reprice_net_cents`, `baseline_rebill_net_cents`, `variant_delta_cents`, `assumed_leak_type`, `excess_gallons`, `current_utc`) also present.
- **Contract 2 — Rule Coverage: PASS.** All 57 error identifiers, all state names, all 65 endpoint paths and all 6 role names present; every transition's preconditions, error pairing and side effects narrated in §3.
- **Contract 3 — §3 Path Purity: PASS.** 971 backticked tokens (284 unique) in §3 scanned: 0 `/`-prefixed tokens, 0 bare HTTP methods, 0 method+path combos; also 0 unbackticked path-like or method tokens in §3 prose.

**Tail check:** confirmed by re-reading the file end after the final append — the last two lines are `| \`ERR_PAYMENT_AMOUNT_INVALID\` | 422 |` and `| \`ERR_TEST_DEPOSIT_INVALID\` | 422 |`, a complete table row at a real section boundary, not mid-sentence.

Two notes on judgement calls: neither withheld design file was opened, and no difficulty phrasing or meta-commentary appears in the document. Where the scaffold's `sewer_relief_basis` helper (three-way minimum including sewer headroom) differed from `leak_adjustment_credit` step 2's simpler two-way minimum, I treated the helper as authoritative since its worked examples reconcile with the credit calculation; and the degenerate field-test window (`window_end` not after `window_start`) is documented as a precondition failure of the scheduling transition returning `ERR_INVALID_STATE_TRANSITION`, since the scaffold declares it among transition preconditions rather than as a field constraint.

**Orchestrator tail re-verification:** independently confirmed — 430 lines, 5 top-level sections at lines 3/11/150/298/370, file ends on the complete table row `| \`ERR_TEST_DEPOSIT_INVALID\` | 422 |`. Not truncated; no regeneration needed.

## Step 6: Generate implementation — 2026-09-03T00:22:00.000Z

Implementation complete and boot-verified.

**Files written** (all in `/home/ubuntu/github/CodingPRD/tasks/task_2465_water_utility_high_bill_investigation_leak_adjustment/workspace/implementation/`):
- `core.py` — in-memory `Store` (13 dict collections, empty on boot), logical clock (epoch `2026-08-01T00:00:00Z`), response envelope, full 57-id error catalogue with statuses, `endpoint()` RBAC decorator (6 roles), `Body`/query validators, pagination, `get_or_404`, customer ownership scoping, Decimal/ROUND_HALF_UP helpers, touch-once-per-request version discipline.
- `calc.py` — the 12 named calculations (tiered water charge with summer tier-3 surcharge, sewer charge + cap, seasonal baseline, anomaly screen, sewer relief, variant selection, dual-variant leak credit with cap/admin-fee, AWWA-weighted vs simple-mean bench accuracy, corrected segment, arrangement schedule, minimum down payment, credit status).
- `domain.py` — read/consumption derivation, submeter sewer credit, bill charge + baseline computation, append-only ledger, balance replay, `refresh_account` (balance → hold counters → credit_status → service_status cascade), rolling 12-month adjustment window check, rebill-pending trigger.
- `routes_a.py` — clock, rate schedules, billing periods, service accounts (+ledger, shutoff, payments), meters, meter readings.
- `routes_b.py` — bills (create/list/get/ledger/adjustment-preview/issue/rebill).
- `routes_c.py` — investigations, meter test requests (field + bench, FAST correction cascade), repair proofs.
- `routes_d.py` — leak adjustments (submit/return/approve/deny/reverse), payment arrangements, board appeals.
- `app.py` — app factory, 4 blueprints, `before_request` touched-set init, ApiError + 404/405/HTTPException handlers emitting the error envelope, `app.run(host="0.0.0.0", port=$PORT)`.
- `start.sh` — guarded flask install, `exec python3 app.py` in the foreground, honours `$PORT` (default 8080). Executable.

**Endpoints implemented: 65** (matches the scaffold's declared count).

**Boot verification**: launched via `PORT=18465 bash start.sh` on a fresh process; a full end-to-end smoke run passed with 0 failures and 0 HTTP 500s / tracebacks — 4 sequential SUMMER bills built a 3-sample baseline of 5000 gal, target bill 30000 gal (water 20700, sewer 8000, total 28700, ratio 6.0, anomaly true), investigation → evidence → verified proof → determination → BASELINE_REBILL adjustment (water 18200, sewer relief 8000 gal/3200, gross 21400, cap 17220 applied, admin fee 1500, net 15720) → approve (bill ADJUSTED, adjusted total 12980, balance 26480 == ledger sum) → payment arrangement activate + installment → reverse (compensating +15720 restoring the pre-approval balance, investigation back to DETERMINED with the hold re-armed) → board appeal (notice-too-short 422, not-yet-held 422, then REVERSE creating a board-ordered PENDING_APPROVAL adjustment superseding the reversed one) → meter test FIELD SUSPECT → BENCH AWWA 105.55 FAST (correction 0.947418, deposit refunded, CORRECTED read written, bill → REBILL_PENDING at 28423 gal). RBAC/401/403/404/400 and pagination envelope checks all returned the expected statuses. A second fresh boot on another port returned empty collections (`total_count: 0`), confirming no seeding and no cross-boot persistence; both servers were killed afterwards and `grep` confirms no file/sqlite/pickle persistence calls anywhere.

## Step 5: Generate unit tests — 2026-09-03T00:32:00.000Z

(Steps 5 and 6 ran concurrently; Step 6's entry above was recorded first only because it returned first.)

The suite is complete and audits clean.

## Files written

**`test_helpers/`** (9 modules, ~3.1k lines) — `constants.py`, `types.py`, `api_errors.py` (all 57 error ids + HTTP status map registered at import), `api_client.py` (one method per declared endpoint + `api_client` singleton), `test_users.py` (six roles; `Customer` is entity-backed via `make_customer_headers(account_id)`), `factories.py` (28 payload builders with an `OMIT` sentinel), `assertions.py`, `fixtures.py` (5-tier composite world builders), `__init__.py`.

**`test_suite/`** — `conftest.py` plus 11 test modules:
`test_01_leak_credit_variants_and_charge_math.py` (14), `test_02_investigation_lifecycle_state_machines.py` (10), `test_03_cascades_and_validation_priority.py` (12), `test_04_boundaries_and_cross_entity_dependencies.py` (19), `test_05_overlap_windows_and_compensating_invariants.py` (19), `test_06_entity_contract_corners.py` (22), `test_07_state_machine_corners.py` (15), `test_08_calculation_and_validation_corners.py` (20), `test_09_endpoint_corners.py` (13), `test_10_error_catalogue_corners.py` (28), `test_11_rbac_concurrency_and_consistency_corners.py` (19).

All under `/home/ubuntu/github/CodingPRD/tasks/task_2465_water_utility_high_bill_investigation_leak_adjustment/`. Total 12,122 lines.

## Test counts

- **Queue A (Difficulty, §1.8):** 74 tests over **24/24** instances — every instance has ≥2 tests (min 2, max 4).
- **Queue B (Corner, §1.9):** 117 tests over **54/54** non-stub instances — every instance has ≥1 test.
- **191 tests total**, collected cleanly by pytest (`191 tests collected`, 0 errors).

## Instances skipped

**None.** All 24 difficulty and all 54 non-stub corner instances passed the PRD-first two-condition filter. Gaps were handled at the *sub-assertion* level instead — individual yaml literals that the PRD does not uniquely derive were dropped rather than weakened. The notable drops:

- `REBILL_ADJUSTMENT` as a `source_kind` (not among the 11 values §2.9 enumerates) — replaced with the PRD-derived `REBILL_REVERSAL` / `REBILL_CHARGE` pair.
- Exact ledger row counts where the yaml undercounted (7 rows, not 6) — replaced with `balance_cents == sum(ledger)`.
- Exact serialization of timestamp fields (`shutoff_scheduled_for`, `effective_at`, `filing_date`, `tested_at`) — asserted by date/instant prefix plus before/after equality, since §2.4 permits three fractional digits.
- "No PUT/PATCH/DELETE is declared" absence-of-surface claims — no observable outcome is specified.
- `due_date` on a *DRAFT* bill (stamped only at issue), `parent_meter_id` default on a master meter, `updated_at` advancing under a frozen logical clock.
- Two yaml recipes were physically impossible/self-contradictory as written and were repaired without changing the asserted outcome: a `CORRECTED` read posted after its own rebilling deadline (would be refused first), and an `ESTIMATED` bill generated from an `ACTUAL` read (§3.2 keys `estimated_flag` off the read).
- Two creates that the yaml labelled HTTP 200 assert **201** per §4.

## Audit results

- **Design tags:** 191/191 tests carry exactly one `Design:` line as the docstring's last line; every tagged name exists verbatim in its source yaml; every tag's section/rule_id matches where the instance actually lives. Zero untagged, dual-tagged, dangling, or stub-tagged tests.
- **Stub discipline:** all **29** `excluded_because:` stubs produce zero tests, and all 29 `difficulty_instance:` pointers resolve to real names in `SCAFFOLD_DIFFICULTY_DESIGN.yaml`.
- **Citations:** every quoted string of ≥8 words in every docstring is a verbatim substring of `workspace/PRD.md` — 0 failures.
- **Hygiene:** no `pytest.mark.skip` / `skipif` / `xfail`, no mocking or monkeypatching, no reference to the scaffold or design files in code/comments, no reference to `workspace/implementation/` (never read).
- **Symbol integrity:** every `api.*`, `fixtures.*`, `assertions.*`, `factories.*`, `constants.*` symbol used by a test exists in the helper it names. All 57 error ids used by tests are registered and are exactly the 57 in the PRD (no extras, none missing).

Not run: pytest execution — no server is up, and the implementation was being generated concurrently.

## Step 7: Run tests and iterate — 2026-09-03T00:52:00.000Z

All 8 rounds are green. Exiting.

## Summary

**Iterations run: 2** (each an 8-round parallel `--isolation per-test-server` sweep under `setsid nohup`).

**Iteration 1** — every round: 184/191, with an identical union of 7 failures across all 8 rounds (fully deterministic, no flakiness signal).
**Iteration 2** — every round: **191/191**.

### Final per-round numbers (iteration 2)
| Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 191/191 | 191/191 | 191/191 | 191/191 | 191/191 | 191/191 | 191/191 | 191/191 |

No `Terminated` in the sweep log; all 8 `results.$i.json` written fresh at 00:45; no runner processes left for this task.

### Tests deleted
**None deleted outright.** One assertion block was removed under STEP 1c (partial-coverage split):

- `test_08_calculation_and_validation_corners.py::test_an_estimated_master_read_suppresses_the_irrigation_submeter_credit` — removed the `consumption_gallons=41000`, `sewer_billable_gallons=12000`, `sewer_charge_cents`/`total_charge_cents` and the two cross-bill delta assertions **on the ESTIMATED bill only**. Category: **computed-field / derivation silence**. PRD §3.2 states verbatim that "`consumption_gallons` is derived from the live `ACTUAL` or `CORRECTED` reads bounding the period", which a faithful reader implements by excluding ESTIMATED reads from the closing bound (yielding 0 for that bill) — while another reader takes the neighbouring sentence ("the `read_type` — `ACTUAL` or `ESTIMATED` — of the period-end read") plus the §3.4 gallon-conservation invariant to include it. Two divergent PRD-faithful implementations are articulable, so the volume/charge figures on an estimated bill are not uniquely derivable. The uniquely-derivable part was kept: `estimated_flag=True` and `submeter_credit_gallons=0` (PRD §3.2: "If the bill's `estimated_flag` is true … `submeter_credit_gallons` is zero"), plus the whole ACTUAL-bill half of the test (41000 gal / 8000 credit / 4000 billable / 2440 sewer) untouched. Driving scaffold rule: `Corner/validations/corner_validation_conditional_estimated_read_suppresses_the_irrigation_submeter_credit`.

### Fixes applied to `test_helpers/`
**None.** All defects were in `test_suite/`.

### Fixes applied to `test_suite/`
- `test_04_boundaries_and_cross_entity_dependencies.py` — three `api.get_meter_reading(ctx["target_read_id"])` calls (in the bench-boundary PASS, the 101.51 FAST and the SLOW tests) were issued with **no auth headers**, so the PRD-required §2.7 tier-1 check correctly returned `ERR_UNAUTHENTICATED` 401 where the test expected 200. Added `TECHNICIAN_HEADERS` (a role listed for `GET /meter-readings/{id}` in PRD §4) and its import. Fixed 3 failures.
- `test_06_entity_contract_corners.py::test_meter_registration_without_account_id_fails_schema_before_reference_lookup` — `factories.master_meter_payload(account["id"], account_id=factories.OMIT, …)` passed the same argument positionally and by keyword → `TypeError` before any request. Rewritten to build the payload and `pop("account_id")`, preserving the intent (missing required field → `ERR_INVALID_REQUEST`).
- `test_06_entity_contract_corners.py::test_invalid_meter_parentage_is_refused_for_every_shape` — same `TypeError` shape on `submeter_payload(..., parent_meter_id=factories.OMIT)`. Rewritten to `pop("parent_meter_id")`, preserving the "omits one for a submeter → `ERR_SUBMETER_PARENT_INVALID`" probe.
- `test_09_endpoint_corners.py::test_account_payment_writes_a_negative_customer_payment_entry_and_clears_past_due` — the call used `validate_success` (hard 200) on `POST /service-accounts/{id}/payments`; the implementation returns 201 with the newly created `AccountLedgerEntry`. PRD §4 ("Successful resource creation returns HTTP 201; … the action endpoints that modify an existing resource … returns HTTP 200") does not uniquely classify this nested write, and the suite's own other call sites for this endpoint (`test_06`, `test_11`) already use the any-2xx `get_success_data`. Switched this one call to `get_success_data`; every asserted rule (PAYMENT/`CUSTOMER_PAYMENT`, `amount_cents=-3000`, null `bill_id`/`source_id`, clock-sourced `effective_at`, balance replay, `CURRENT`/`ACTIVE`, filtered listing) is unchanged.

### Fixes applied to `implementation/`
**None required.** No implementation defect was found: all 7 failures traced to test-side bugs or to a PRD-underdetermined assertion. No endpoint, field, side effect or check was added, removed or weakened, and storage remains in-memory with no seeding.

**Orchestrator verification:** independently re-read all 8 `results.*.json` (timestamped 00:45) — each reports `passed=191, total=191, failed=0`. Confirmed.

**Step 8 skip decision:** NOT skipped. The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes. Step 7 applied 4 `test_suite/` fixes and one partial-coverage assertion removal, so PRD-silence sites exist even though `implementation/` needed no change. Step 8 runs with those items as its `<step_7_diff>`.

## Step 8: Finalize PRD — 2026-09-03T00:58:00.000Z

`PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_2465_water_utility_high_bill_investigation_leak_adjustment/workspace/PRD_FINALIZED.md`.

## Size
- PRD.md: 430 lines / 12,663 words. PRD_FINALIZED.md: 430 lines / 12,910 words.
- Line delta: **0%** (all three edits are inline inside existing paragraphs). Word delta: **+1.95%**.

## Changes (3)
- **§3.2 (Generating and Issuing a Bill)** — *revise* — pinned the master consumption derivation: only a live `ACTUAL`/`CORRECTED` read may bound the period (an `ESTIMATED` read never can), opening = greatest such read at or before `start_date` falling back to `initial_register_value`, closing = greatest such read inside the closed-closed period window (latest-created wins a `read_date` tie), difference floored at zero, and **zero consumption when no eligible closing read exists** — which is what an `ESTIMATED` period-end read leaves behind, with all volume/charge fields following from that zero. `implementation/domain.py:120-148` (`opening_read_value` / `closing_read_value` / `derive_consumption`, `LIVE_READ_TYPES` at `domain.py:24`), consumed at `domain.py:201`.
- **§3.4 (FAST cascade, link two)** — *revise* — scoped the gallon-conservation identity to meters whose reads are all `ACTUAL`/`CORRECTED`, and marked it a consequence of the §3.2 derivation rather than an independent rule, so a period whose only period-end read is `ESTIMATED` bills zero without the identity being patched up. `implementation/domain.py:141-148` vs `domain.py:98-100` (`latest_live_read` uses all read types).
- **§4 preamble (Endpoint Definitions)** — *revise* — pinned `POST /service-accounts/{id}/payments` as a creation: HTTP **201** returning the newly written `AccountLedgerEntry` (not the account), added as a second exception alongside rebill to "action endpoints return the resource they acted upon". `implementation/routes_a.py:345-366` (`created_response(serialize(entry))`), `implementation/core.py:468-476`.

No PRD edit for the `test_04` missing-auth-header fixes (PRD §2.7 tier 1 already determines the 401) or the two `test_06` `TypeError` fixture bugs (PRD §3.1 already pins missing-field → `ERR_INVALID_REQUEST` and submeter-without-parent → `ERR_SUBMETER_PARENT_INVALID`, and `routes_a.py:372-410` matches).

## Per-edit pre-edit search log
**Edit 1 — §3.2 consumption derivation**
- (a) Subject: how a bill's `consumption_gallons` is derived from meter reads, and which read types are eligible as period bounds.
- (b) Enumerated/read: `domain.py:24` `LIVE_READ_TYPES`, `domain.py:82-107` (`all_reads`, `live_reads`, `latest_live_read`, `nearest_live_read_before`), `domain.py:114-148` (`consumption_since_prior`, `opening_read_value`, `closing_read_value`, `derive_consumption`), `domain.py:154-188` `submeter_credit_gallons` (uses the same ACTUAL/CORRECTED filter for its own bounds), sole writer `domain.py:194-214` `compute_bill_charges` and all three of its callsites — `routes_b.py:109` (generation), `routes_b.py:276` (rebill replacement), `domain.py:262-277` `trigger_rebill_pending` (CORRECTED read and FAST cascade); plus the paths that *do* honour `ESTIMATED` reads: `routes_a.py:511-522` (negative-consumption floor + `consumption_since_prior_gallons`), `routes_c.py:505-532` `_apply_fast_correction` (target chosen with `types=None`), `routes_a.py:576-579` (`live_only` filter).
- (c) Adjustment: scoped the exclusion strictly to the *bounding* role rather than to liveness, and after re-checking the non-bounding paths replaced "remains a live row for every other purpose" with "is otherwise an ordinary live row" so the sentence makes no universal claim about the floor check, `consumption_since_prior_gallons`, the FAST-cascade target or the `live_only` listing (all of which do include `ESTIMATED` rows).

**Edit 2 — §3.4 conservation identity**
- (a) Subject: the claimed equality between summed billed `consumption_gallons` and register travel.
- (b) Enumerated/read: `domain.py:141-148` `derive_consumption`, `domain.py:98-100` `latest_live_read` (all read types, so an `ESTIMATED` read can be the greatest live `reading_value`), `routes_c.py:505-532` FAST cascade (`prior_value + segment` keeps the register monotonic and can turn an `ESTIMATED` target into a `CORRECTED`, hence *bound-eligible*, row), `routes_a.py:471-547` manual `CORRECTED` posting (caller-supplied `reading_value`), `domain.py:262-277` bill recompute, `test_suite/test_05...py:439` (all-`ACTUAL` scenario the identity still holds for).
- (c) Adjustment: weakened rather than deleted — added the "reads are all `ACTUAL` or `CORRECTED`" antecedent and dropped "always", so the sentence now claims strictly less than before and cannot contradict either the FAST/manual-correction paths or the estimated-period gap.

**Edit 3 — §4 success status / returned resource**
- (a) Subject: which HTTP status and which resource each successful operation returns.
- (b) Enumerated/read: `core.py:468-476` (`object_response` 200 / `created_response` 201), and every POST route with its return: `routes_a.py:62` (clock echo, 200), `111`, `168`, `253`, `428`, `547` (creations, 201), `203`, `214`, `282`, `318`, `342` (actions, 200 + acted-on row), `366` (**payments → 201 + ledger entry**); `routes_b.py:111` (201), `238` (issue, 200 + bill), `281` (rebill, 200 + replacement); `routes_c.py:111`, `300`, `568` (201) and `165`, `201`, `230`, `396`, `434`, `502`, `629`, `655` (200); `routes_d.py:151`, `466`, `642` (201) and `223`, `237`, `299`, `329`, `377`, `537`, `572`, `590`, `711`, `797` (200). Also checked the other ledger-writing actions (`routes_b.py:211-238` issue, `routes_d.py` approve/reverse/activate/record-payment) to confirm they stay 200 + parent resource.
- (c) Adjustment: wrote the exception as specific to the account-payment endpoint (not as a general "nested write" or "any ledger-writing endpoint" rule), since `meter-test-requests` creation is already a plain 201 create and every other ledger-writing action returns 200 with its parent.

## Step 9: Complete PRD — 2026-09-03T01:20:00.000Z

`PRD_COMPLETED.md` is finished and verified.

## Counts

| | |
|---|---|
| `PRD_FINALIZED.md` (source) | 430 lines, 95,727 chars |
| `PRD_COMPLETED.md` | 430 lines, 111,266 chars |
| Char delta | **+15,539** |
| Changed line-groups | 46 (47 lines); same line count, no new sections, no new paragraphs — every change is an in-paragraph insert or revision |
| Ambiguity pins | 36 |
| Mismatch revisions | 15 |
| Final line | `| ERR_TEST_DEPOSIT_INVALID | 422 |` — §5 table intact, not truncated |

## Changes

- §2.2 — insert — ambiguity — `api_request_id` is `req_` + 20 chars from upper-case letters and digits — `core.py:455-461`
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not the host wall clock — `core.py:461`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` is 400; empty value falls back to the default; undeclared query params ignored; `has_more` = `offset + len(rows) < total_count` — `core.py:651-667, 485`
- §2.3 — insert — ambiguity — insertion order is the final tie-break on all three ordering rules — `core.py:447-448`, `domain.py:78-86`
- §2.4 — insert — ambiguity — a row is refreshed at most once per request and a row the request created stays at `version` 1 — `core.py:414-434`
- §2.4 — insert — ambiguity — clock epoch `2026-08-01T00:00:00Z`; the setter echoes `current_utc` as its sole `data` field and ignores both auth headers outright — `core.py:273`, `routes_a.py:56-61`
- §2.7 — revise — mismatch — the tier-3 enumeration is a set, not a sequence; in both operations carrying two tier-3 rules the cross-field comparison precedes the uniqueness check — `routes_a.py:86, 142-145`
- §2.9 — insert — ambiguity — both hold counters are recounted from scratch, never incremented; refresh order is balance → counters → credit → service; the row is written only when one of six values changed — `domain.py:345-397`
- §2.10 — revise — **mismatch** — billing-period check order is `end_date < start_date` **then** duplicate `period_code`, not the reverse — `routes_a.py:142-145`
- §2.11 — insert — ambiguity — boolean filters accept any letter case; enum and `hearing_date` filters reject bad shapes with `ERR_INVALID_REQUEST` — `core.py:677-707`
- §3.1 — insert — ambiguity — rate-schedule tier ordering is checked before `code` uniqueness — `routes_a.py:86-89`
- §3.1 — insert — ambiguity — `size_inches` is a number with an exclusive zero minimum — `routes_a.py:379`
- §3.1 — insert — ambiguity — `corrects_reading_id` need only exist: not required to be on the same meter, not required to be live, superseding is unconditional — `routes_a.py:489-491, 537-539`
- §3.1 — revise — **mismatch** — the `LOCKED` and `REBILL_WINDOW_EXPIRED` gates key on the period containing `read_date` alone (no bill lookup), are skipped when no period contains it, and run **before** the future-date check — `routes_a.py:493-508`
- §3.1 — insert — ambiguity — the rebill trigger picks the earliest-created qualifying bill and is a silent no-op when none qualifies — `domain.py:262-277`
- §3.2 — revise — **mismatch** — bill generation creates **no** `MeterReading`; `read_type` is merely recorded — `routes_b.py:71-107`
- §3.2 — revise — **mismatch** — `estimated_flag` is a copy of the supplied `read_type`, never re-derived from the reads — `routes_b.py:107`
- §3.2 — revise — **mismatch** — the duplicate-bill check runs before both meter checks — `routes_b.py:88-100`
- §3.2 — insert — ambiguity — `ESTIMATED` reads are never eligible as a period bound; no eligible closing read ⇒ zero consumption; created-order tie-break on the closing read — `domain.py:120-148`
- §3.2 — insert — ambiguity — a `DRAFT` bill has `due_date` null and writes nothing to the ledger — `routes_b.py:35-66`
- §3.2 — revise — mismatch — a `LOCKED` period at issue time is `ERR_INVALID_STATE_TRANSITION`, not `ERR_BILLING_PERIOD_LOCKED` — `routes_b.py:231-234`
- §3.3 — insert — ambiguity — a bill not in `ISSUED` is reported as `ERR_INVESTIGATION_ALREADY_OPEN` — `routes_c.py:72-76`
- §3.3 — insert — ambiguity — neither evidence form is gated on investigation status; only the advance is conditional and is otherwise a fully silent no-op — `routes_c.py:52-57, 538-567`
- §3.3 — insert — ambiguity — both proof-review actions require `EVIDENCE_UNDER_REVIEW` after the proof's own `SUBMITTED` check; the `repair_date` floor is also `ERR_INVALID_STATE_TRANSITION` — `routes_c.py:609-630`
- §3.3 — insert — ambiguity — the closure instant is held internally and never serialized on the investigation — `routes_c.py:219`
- §3.4 — insert — ambiguity — investigation status is not consulted on a test request; deposit ledger entry only when > 0; `BENCH` self-advance happens after that entry — `routes_c.py:236-299`
- §3.4 — revise — ambiguity — scheduling failures (state, type, `window_end` ≤ `window_start`) are all `ERR_INVALID_STATE_TRANSITION`; order is state/type → window sanity → quarantine → conflict; touching endpoints do not conflict — `routes_c.py:355-389`
- §3.4 — insert — ambiguity — field `PASS` writes only `accuracy_status` and `last_test_completed_at`, leaving `accuracy_pct` and `correction_factor` untouched — `routes_c.py:421-427`
- §3.4 — insert — ambiguity — bench flow points are plain numbers; recording a bench result nulls both windows — `routes_c.py:441-444, 468-469`
- §3.4 — insert — ambiguity — cascade link two targets the latest live read regardless of `read_type` (an `ESTIMATED` read is eligible) and stops silently when the meter has no live read — `routes_c.py:505-509`
- §3.4 — insert — ambiguity — cascade link three is best-effort: skipped on no period / `LOCKED` / no eligible bill, never refusing the bench result; earliest-created bill wins — `domain.py:262-277`
- §3.5 — revise — **mismatch** — the manual correction is refused with `ERR_BILLING_PERIOD_LOCKED` while the meter-test path merely declines to move a bill — `routes_a.py:495-500` vs `domain.py:263-265`
- §3.5 — insert — ambiguity — the replacement bill copies `estimated_flag` and computes its own baseline/anomaly fields from scratch — `routes_b.py:268-277`
- §3.6 — insert — ambiguity — `determine` reports the null baseline and both evidentiary preconditions as `ERR_INVALID_STATE_TRANSITION`, in a pinned order — `routes_c.py:174-193`
- §3.6 — insert — ambiguity — `assumed_leak_type` is a mandatory query param validated before the bill 404; the preview is ungated on `billing_status`; a null baseline is taken as zero — `routes_b.py:181-192`, `calc.py:107`
- §3.7 — insert — ambiguity — submit's three preconditions are all `ERR_INVALID_STATE_TRANSITION`, not the dedicated proof/leak-type codes used at drafting — `routes_d.py:203-218`
- §3.7 — insert — ambiguity — deny carries the same SOD and `LOCKED` guards as approve (minus the ceiling); return carries neither — `routes_d.py:302-320, 226-238`
- §3.7 — insert — ambiguity — `APPROVED` is never persisted; stored status is `POSTED` with `version` +1 for the whole approval — `routes_d.py:283-287`
- §3.7 — insert — ambiguity — a bill not in `UNDER_INVESTIGATION` keeps its status while still recomputing `adjusted_total_cents`, and is touched either way — `routes_d.py:289-292`
- §3.7 — revise — **mismatch** — on reverse, `adjusted_total_cents` is recomputed by the `POSTED`-sum rule and only returns to `total_charge_cents` when no other adjustment is still `POSTED`; the bill moves only from `ADJUSTED` — `routes_d.py:363-366`
- §3.8 — insert — ambiguity — both schedule-shutoff preconditions are `ERR_INVALID_STATE_TRANSITION` — `routes_a.py:305-312`
- §3.8 — revise — **mismatch** — the three system `service_status` transitions are one ordered chain with the return to `ACTIVE` tested first — `domain.py:377-387`
- §3.8 — revise — **mismatch** — execute-shutoff order is credit_status → holds → notice (not notice-first); a null `shutoff_scheduled_for` skips the notice check — `routes_a.py:325-338`
- §3.8 — insert — ambiguity — the four arrangement business rules run in the stated order, all after the version check, with the bill checked before the investigation — `routes_d.py:402-431`
- §3.8 — insert — ambiguity — proposing a plan always writes the account row, so its `version` rises even when nothing derived changed — `routes_d.py:462`
- §3.8 — revise — **mismatch** — activation writes the down-payment entry unconditionally, producing a zero-cent ledger row when `down_payment_cents` is 0; the precondition failure is `ERR_INVALID_STATE_TRANSITION` — `routes_d.py:516-535`
- §3.8 — revise — **mismatch** — `COMPLETED` is tested before `DEFAULTED`, so a late final instalment completes rather than defaults; `ERR_PAYMENT_AMOUNT_INVALID` is checked after the `ACTIVE` status, and the amount is never reconciled against the schedule — `routes_d.py:552-569`
- §3.9 — insert — ambiguity — `filing_date` is a full ISO instant (its calendar date drives the notice arithmetic); a missing reference instant is `ERR_INVALID_STATE_TRANSITION`, checked between the status gate and timeliness — `routes_d.py:611-626`
- §3.9 — insert — ambiguity — the docket counts only *other* appeals in `SCHEDULED`, so decided appeals free their slot — `routes_d.py:697-707`
- §3.9 — revise — **mismatch** — record-decision order is state → REVERSE verified-proof → `ERR_HEARING_OFFICER_CONFLICT` → `ERR_HEARING_NOT_YET_HELD` → `ERR_REMAND_LIMIT_EXCEEDED` — `routes_d.py:723-741`
- §3.9 — insert — ambiguity — `UPHOLD` leaves a bill not in `UNDER_INVESTIGATION` exactly as it stands — `routes_d.py:751-754`
- §3.9 — revise — **mismatch** — the board-ordered adjustment stamps `created_by_user_id` with the clerk's `X-User-ID`, starts every reason/approval field null, and leaves the bill's status untouched — `routes_d.py:766-776`
- §3.9 — insert — ambiguity — `REMAND` increments `evidence_round_count` with no ceiling check, so it can reach four — `routes_d.py:787`

## Cross-checks with no change needed

- **§4 endpoint table** — all 65 routes (paths, methods, role lists) match the blueprints exactly.
- **§5 error catalogue** — all 57 codes and HTTP statuses match `core.ERROR_STATUS` byte-for-byte (verified programmatically).
- **§2.5 / §3.6 calculations** — every formula in `calc.py` (tiered charge, sewer cap-then-credit, baseline, anomaly, six credit steps, cap, admin fee, bench accuracy, instalment schedule, credit status) already matched the PRD uniquely.

**Orchestrator verification:** `PRD_COMPLETED.md` present — 430 lines / 111,266 chars, 5 top-level sections at lines 3/11/150/298/370, ends on the complete §5 table row `| \`ERR_TEST_DEPOSIT_INVALID\` | 422 |`. Not truncated. Pipeline complete through Step 9.
