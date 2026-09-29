# Worklog — task_2600_move_concierge_utility_address_change_automation

## Step 1: Create task directory — 2026-09-03T17:58:50.238Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2600_move_concierge_utility_address_change_automation` and its `workspace/` subdirectory. Index 2600 was pre-assigned by the orchestrating prompt; no scan of `./tasks/` was performed (32 pipelines run concurrently on this host, so auto-allocation would collide).

## Step 2: Generate scaffold — 2026-09-03T19:58:26.968Z

Scaffold generation for task_2600 is complete and lint-clean.

## Output files
`/home/ubuntu/github/CodingPRD/tasks/task_2600_move_concierge_utility_address_change_automation/`
- `SCAFFOLD.yaml` — **3074 lines** (§1.0–§1.7 only; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — **2806 lines** (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — **5361 lines** (single key `scaffold_corner_design`)

## SCAFFOLD.yaml surface
14 entities, 64 endpoints, 58 error codes, 50 ordered validations, 8 state machines over 7 entities (UtilityOrder carries two parallel dimensions: `provision_status` × `credit_status`), 3 OCC concurrency rules, 5 calculations (4 with dual variants), 8 roles. Profile: `workflow_orchestration` / `compliance_audit`, graph topology, parallel state-machine shape, `segregation_of_duties` role model layered on four entity-backed peer-ownership roles, saga consistency.

## §1.8 — 9 rules / 29 instances
`dual_variant_calc` 4, `boundary_precision_check` 4, `combinatorial_formula` 3, `non_linear_state_machine` 3, `transitive_cascade` 3, `priority_pair_validation_conflict` 3, `cross_entity_state_dependency` 3, `resource_temporal_overlap` 3, `compensating_invariant` 3.

## §1.9 — 9 sections / 99 instances (66 full recipes + 33 `excluded_because` stubs)
entities 12, state_machines 18, calculations 14, validations 29, endpoints 6, errors 5, rbac 5, cross_cutting_complexity_layers 7, consistency_model 3.

## Lint
`VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (1443 calls scanned).

## Consistency repairs made to SCAFFOLD.yaml while writing §1.9
- Validation 39 / `ERR_TYPE_ALREADY_MAPPED` / the mapping endpoint's side-effect / the `VERIFIED_to_SCHEDULING` note were all rescoped so re-mapping only blocks on orders in `{DRAFT, SCHEDULED, ACTIVE_SERVICE, SUSPENDED}` — previously the `ATTENTION_REQUIRED` self-loop (and therefore the `ERR_UNRESOLVED_PROVISION_FAILURE` repair path) was unreachable.
- Validation 2 now states that `exclusive_operations` reservations are enforced at operation level, making `method: MANUAL_OVERRIDE` a ComplianceOfficer/PlatformAdmin-only body value on a path MoveOpsAgent may otherwise use.
- `move_readiness_score`'s `post_verification` variant now also covers the `CANCELLED` and `DUPLICATE_MERGED` terminal states (previously neither variant applied to them).
- `NON_TERMINAL_to_CANCELLED` actor list corrected to match the endpoint's roles (`MoveOpsAgent | FeedIntegrator | PlatformAdmin`).

Verified additionally: all 58 error codes are triggered somewhere across §1.8/§1.9 (only 2 exclusively in §1.8), instance names unique across both design files, every stub cites a real §1.8 instance in `rule_id / instance_name` form with no `test_recipe`, all `grounds` resolve to real entities/fields/transition ids/priorities/endpoints, and no forbidden concurrency vocabulary remains. The hard constraint held: no sibling task directory was read, listed, or grepped at any point.

Orchestrator verification: all three files parse as valid YAML with the expected top-level keys (`SCAFFOLD.yaml` has no design key; the other two carry exactly `scaffold_difficulty_design` / `scaffold_corner_design`).

## Step 3: Copy shared files — 2026-09-03T19:58:46.718Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T20:16:52.870Z

All sections are written and verified. Final state confirmed.

**Deliverable:** `workspace/PRD.md` — **507 lines**, ending at a genuine section boundary (last row of the §5 error table, `ERR_SETTLEMENT_AMOUNT_INVALID | 422`).

## Ordered headings

1. `# Move Concierge Utility Automation API — Product Requirements Document`
2. `## 1. Introduction`
3. `## 2. Global Specifications & System-Wide Principles` (2.1 Actors/Headers/RBAC, 2.2 API Response Structure, 2.3 Pagination and List Ordering, 2.4 The Logical Clock, 2.5 Common Resource Properties, 2.6 Path Resolution and Reference Validation, 2.7 Validation Precedence, 2.8 Optimistic Concurrency on Residents and Moves, 2.9 Cascade Discipline and Conserved Quantities, 2.10 Precision/Rounding/Score Ranges, 2.11 Segregation of Duties and the Audit Trail)
4. `## 3. Business Logic & Workflows` (3.1 Configuring the Concierge Network, 3.2 Move Intake and Duplicate Detection, 3.3 Verifying the Mover's Identity, 3.4 Data-Sharing Consent and the Consent Gate, 3.5 Mapping Providers and Scheduling Service Windows, 3.6 Credit Handoff/Deposits/Activation/Failure, 3.7 Redirecting the Mail: Postal Change-of-Address Filings, 3.8 Referral Placements/Attribution/Revenue Share, 3.9 Readiness Scoring/Attention Clearance/Completion/Cancellation)
5. `## 4. Endpoint Definitions`
6. `## 5. Error Code Catalogue`

## Coverage

- **14/14 entities** — every entity name appears in the prose; `RevenueShareLedgerEntry` is explicitly called out in §2.5 as the one entity carrying only `id` and `created_at`.
- **64/64 endpoints** — §4 table has exactly 64 data rows and exactly 4 columns; 12 creation endpoints named as HTTP 201 in the intro paragraph, all others 200.
- **58/58 error codes** — §5 table has exactly 58 data rows; additionally all 58 ids appear in the §2/§3 prose before §4, so none is orphaned in the catalogue.
- **50/50 validations** — rendered as the explicit numbered precedence ladder in §2.7 (rule → `error_id` → HTTP status → `applies_to` scope).
- **8/8 state machines, 56/56 transitions** — every `from`/`to` state value of all eight machines (`MoveRecord.lifecycle_status`, `IdentityVerification.status`, `UtilityOrder.provision_status`, `UtilityOrder.credit_status`, `CreditCheckHandoff.handoff_status`, `AddressChangeFiling.status`, `ReferralPlacement.placement_status`, `ConsentRecord.state`) appears backticked in the prose, including both self-loops, all three `ATTENTION_REQUIRED` cascade variants, the `REJECTED → SUBMITTED` cycle, and all four compensating `VOIDED` exits.
- **5/5 calculations** — `duplicate_match_score`, `move_readiness_score`, `credit_deposit_amount_cents`, `referral_attributed_share_cents`, `identity_kba_evaluation`, each with all variants and worked numbers (57 / 70 / 40; 22500 / 18000 / 13500; 27000 / 4725 / 22275 plus the +3000 / −525 settlement deltas; 176+176 = 352). Every declared constant value appears in the prose.
- **8/8 roles** — all named in §2.1 with the four entity-backed identity bindings and four opaque-operator roles.
- **3/3 concurrency rules** — all three OCC rules with write operation, `expected_resident_version` / `expected_move_version`, error id and 412.

## Hard Contract reports

**Contract 1 — Field-Name Coverage: PASS.** 136 required identifiers (123 entity field names across 14 entities plus 103 endpoint input/query/path identifiers, deduplicated) checked mechanically against the set of backticked tokens in PRD.md. Missing: none.

**Contract 2 — Rule Coverage: PASS.** 50/50 validation priorities with error id, status and scope; 3/3 OCC rules; 56/56 state transitions with preconditions and side effects; 5/5 calculations with all variants, constants, rounding rules and pinned evaluation orders (readiness snapshot freeze, round-per-placement-then-sum); all multi-hop cascades (consent revocation 3-hop, marketing opt-out, provision failure 3-hop, credit decline 2-hop, move cancellation, duplicate merge 4-hop, gate-reopen restoration); all field defaults and initial values; sibling-branch symmetry given equal density.

**Contract 3 — §3 Path Purity: PASS.** 298 distinct backticked tokens in §3 (lines 199–374) scanned: zero tokens beginning with `/`, zero bare HTTP methods, zero method+path combinations.

Also verified: §2.2 is byte-identical to `section-2.2-response-structure.md`, and none of the forbidden fuzzy words appears anywhere. Per the hard constraint, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml` and all sibling task directories were never opened or grepped.

Orchestrator anti-truncation check: independently confirmed 507 lines, 26 headings in the expected order, endpoint table = 64 method rows, error table = 58 `ERR_` rows, and the file's last line is a complete table row (`| \`ERR_SETTLEMENT_AMOUNT_INVALID\` | 422 |`) — not truncated mid-sentence. No regeneration needed.

## Step 6: Generate implementation — 2026-09-03T21:32:00.000Z

Implementation of task 2600 is complete, compiles, boots from a fresh process, and passes an end-to-end smoke suite.

## Files written (all under `workspace/implementation/`)

`start.sh` 8, `requirements.txt` 1, `app.py` 84, `db.py` 152, `errors.py` 100, `response.py` 126, `middleware.py` 71, `validators.py` 171, `routes/__init__.py` 0, `routes/config.py` 363, `routes/moves.py` 476, `routes/identity.py` 78, `routes/orders.py` 356, `routes/filings.py` 244, `routes/consents.py` 129, `routes/placements.py` 309, `routes/clock.py` 20, `services/__init__.py` 0, `services/enums.py` 180, `services/lookup.py` 160, `services/derive.py` 250, `services/duplicates.py` 201, `services/deposits.py` 63, `services/revenue.py` 73, `services/cascades.py` 184, `services/gates.py` 187, `services/mapping.py` 113, `services/scheduling.py` 83.

Total 4182 lines, 26 Python modules + `start.sh` + `requirements.txt`. `__pycache__` removed.

## How the surface is distributed

**64 endpoints** (verified: `app.url_map` yields exactly 64 non-static method/rule pairs): `routes/config.py` 17 (FeedSource, Resident, ServiceAddress, UtilityProvider, ProviderServiceTerritory, ReferralPartner CRUD + status/preference patches), `routes/moves.py` 11 (create/read/list, readiness, identity-verification open, provider-mapping, duplicate-resolution, cancellation, attention-clearance, completion, consent-evaluation), `routes/orders.py` 12 (order read/list, schedule, credit-checks, handoff read/list, bureau-response, deposit-payments, activation, provision-failure, closure, waiver), `routes/placements.py` 10 (create/read/list, acceptance, decline, conversion, settlement, reversal, ledger read/list), `routes/filings.py` 6, `routes/consents.py` 4, `routes/identity.py` 3, `routes/clock.py` 1.

**50-rung validation ladder**: rung *predicates* are centralized as reusable guards in `services/gates.py` (move actionability, both OCC rules, consent presence, gate-open, duplicate resolution, identity currency, placement/filing/order state) with field-shape rungs in `validators.py`; each route calls them in explicit ladder-priority order, with the priority number named in a comment at each call site.

**8 state machines**: MoveRecord lifecycle in `routes/moves.py` + `services/derive.py` (`try_bubble_up`, `park_attention`, `refresh`); UtilityOrder's two parallel dimensions (provision_status × credit_status) in `routes/orders.py` with dimension-crossing hops in `services/cascades.py`; CreditCheckHandoff in `routes/orders.py`; AddressChangeFiling in `routes/filings.py`; ReferralPlacement in `routes/placements.py`; ConsentRecord in `routes/consents.py`; IdentityVerification in `routes/identity.py`. All compensating cascades (suspension/restoration, waiver, provision-failure, cancellation, duplicate-merge, marketing opt-out) live in `services/cascades.py`, each hop bumping `version` + `updated_at`.

**5 calculations**: `services/duplicates.py` (duplicate_match_score, both passes), `services/derive.py` (move_readiness_score pre/post variants), `services/deposits.py` (credit_deposit_amount_cents, estimate_at_mapping vs final_at_bureau_response off a frozen readiness snapshot), `services/revenue.py` (referral_attributed_share_cents provisional/settled + immutable ledger + feed accrual), `routes/identity.py` (identity_kba_evaluation). All money/score arithmetic uses `Decimal` with ROUND_HALF_UP; no floats.

Storage is in-memory only (14 dicts in `db.py`), nothing seeded — verified empty at boot. Time comes solely from `db.db.clock` (default `2026-08-01T00:00:00Z`), settable via `POST /_clock/set_current_utc`. `start.sh` reads `$PORT`, binds 0.0.0.0, runs in the foreground.

## Smoke test

Server launched on explicitly-checked-free ports 18600 and 18607, driven through four scripted scenario rounds, then killed by its own PID resolved from that specific port (no pattern kills).

Happy paths confirmed: mapping → order creation, scheduling, credit handoff → bureau response, deposit payment, activation, closure, filing draft → submit → USPS confirm (and reject → resubmit with `resubmit_count` 1), placement → conversion → settlement/reversal, attention-clearance recovery.

Numerics confirmed: `forward_end_date` 2027-08-19 from 2026-08-20 (365−1); deposit 22500 = 15000 × 1.50 (score 590) × 1.00; REV_SHARE_PCT commission 27000 with 6750 feed share at 25%; FLAT_BOUNTY 7500 flat with 1500 feed share at 20%; ledger net 6000 after settlement and exactly 0 after reversal with feed accrual returning to 0.

Error paths confirmed (24 distinct codes): 401 missing auth, 403 `ERR_FORBIDDEN_ROLE`/`ERR_OWNERSHIP_VIOLATION`, 404 `ERR_NOT_FOUND`, 405 `ERR_METHOD_NOT_ALLOWED`, 412 `ERR_STALE_RESIDENT_VERSION`, plus `ERR_MOVE_NOT_ACTIONABLE`, `ERR_IDENTITY_NOT_VERIFIED`, `ERR_VERIFICATION_ATTEMPTS_EXHAUSTED`, `ERR_TYPE_ALREADY_MAPPED`, `ERR_MISSING_ACCOUNT_DATA`, `ERR_LEAD_TIME_VIOLATION`, `ERR_INVALID_SERVICE_WINDOW`, `ERR_SERVICE_WINDOW_CONFLICT` (touching windows correctly allowed), `ERR_ACTIVATION_TOO_EARLY`, `ERR_DEPOSIT_CAP_EXCEEDED`, `ERR_UNRESOLVED_PROVISION_FAILURE`, `ERR_FILING_NOT_SUBMITTABLE`, `ERR_TERRITORY_OVERLAP`, `ERR_DUPLICATE_VERTICAL_PLACEMENT`, `ERR_ATTRIBUTION_WINDOW_EXPIRED`, `ERR_SETTLEMENT_AMOUNT_INVALID`, `ERR_CONSENT_MISSING`, `ERR_MOVE_DATE_OUT_OF_RANGE`, `ERR_INVALID_REQUEST`.

Two bugs found and fixed during smoke testing: a fresh `PARTNER_MARKETING` grant reopened the consent gate but left `blocked_reason` stuck at `CONSENT_REVOKED` (fixed in `services/cascades.py:apply_consent_restoration`); `close_order` wrote an undeclared `final_read_note` field into responses (now validated then discarded). Three apparent failures turned out to be wrong expectations in the subagent's own driver script, not implementation defects — the route is `address-change-filings` (not `address-filings`), `filing_type` is `INDIVIDUAL|FAMILY|BUSINESS`, and the payout model is `REV_SHARE_PCT` with `rev_share_pct`.

## Step 5: Generate unit tests — 2026-09-03T22:44:00.000Z

Test generation for task_2600 is complete. Both directories are at the task root; nothing was written under `workspace/`, and `workspace/implementation/` was never read or touched.

## test_helpers/ — 9 files, 2,869 lines
`__init__.py` 119 · `api_client.py` 418 (65 methods: all 64 declared endpoints + `raw_request`) · `api_errors.py` 132 (all 58 error ids + HTTP map, registered via `set_error_http_status_map`) · `assertions.py` 334 · `constants.py` 113 · `factories.py` 567 · `fixtures.py` 568 (5 tiers, identity-threaded) · `test_users.py` 127 · `types.py` 491 (31 enums + 14 resource shapes).

## test_suite/ — conftest + 19 test files, 10,100 lines, 201 tests
`conftest.py` 68 · `test_01_dual_variant_divergence` 406/8 · `test_02_composed_formula_arithmetic` 363/6 · `test_03_parallel_and_cyclic_state_paths` 509/8 · `test_04_multi_hop_cascades` 428/10 · `test_05_validation_ladder_precedence` 360/6 · `test_06_threshold_boundaries` 563/10 · `test_07_cross_entity_state_gates` 547/8 · `test_08_temporal_occupancy_rules` 546/8 · `test_09_compensating_unwinds` 511/6 · `test_10_resource_shapes_and_defaults` 621/16 · `test_11_state_machine_transitions` 793/15 · `test_12_calculation_constants_and_precision` 580/12 · `test_13_validation_rules_intake_and_scheduling` 720/16 · `test_14_validation_rules_filing_and_referral` 790/16 · `test_15_endpoint_behaviours` 659/16 · `test_16_error_catalogue_shape` 329/11 · `test_17_role_based_access_control` 522/15 · `test_18_concurrency_and_derived_fields` 494/10 · `test_19_saga_compensation` 291/4.

## Coverage against the two design indices
- **Queue A (difficulty): 29/29 instances translated, 0 skipped**, every one with >=2 tests (76 tests across files 01–09).
- **Queue B (corner): 66/66 non-stub instances translated, 0 skipped** (125 tests across files 10–19). None of the 33 `excluded_because` stubs was translated.

## Machine-verified audit (whole suite)
- 201 tests, every docstring ending in exactly one `Design:` line; **0 untagged, 0 dual-tagged, 0 dangling** (tags reconciled against both yaml files), 0 stub tags.
- All 298 quoted PRD spans confirmed as literal whitespace-normalised substrings of `workspace/PRD.md`; every test carries at least one >=8-word verbatim citation.
- `pytest --collect-only`: 201 collected, 0 errors. `py_compile` clean; `pyflakes` clean on all of `test_suite/`.
- No occurrence of "scaffold", "design instance", `pytest.skip`, `xfail`, or TODO anywhere in the generated code.

## Judgement calls worth flagging (PRD beat the design recipe)
1. Several recipes scheduled an order *before* dispatching its credit check; the PRD requires dispatch from `provision_status` `DRAFT`, so those setups were reordered — which freezes `readiness_snapshot` at 40 and yields the PRD's own worked 18000 rather than the recipe's 15000/9900.
2. Removed one weakened assertion left in `test_11` (`assert early.status_code != 200` for closure before `scheduled_window_end`): the PRD attaches no error id to that precondition, so per skip-don't-weaken the sub-assertion is gone and the test keeps only the derivable positive path.
3. Dropped sub-assertions where the PRD is silent or self-contradictory: `rev_share_pct` 0.95 (§2.7 says <=1.0000, §2.10/§3.1 say <=0.9000), 422 for server-owned body keys on move creation (rule 6 enumerates only required/enum/range/format), and `blocked_reason` returning to `NONE` on consent restoration.
4. Two recipes were unreachable as written and were re-aimed at the same rule via a legal path: declining a placement requires `ACCEPTED` (not `PLACED`), and the duplicate-hold cascade is proven against opening an identity verification because rung 7 would preempt rung 27 for mapping.

The suite had not been executed against a server at this point — the Step 6 implementation agent was still generating `workspace/implementation/` while this ran.

Orchestrator note on ordering: Steps 5 and 6 were launched in a single assistant message so they ran concurrently, giving the implementation generator physical isolation from `test_suite/` (the directory did not exist when it started). Verified afterwards that `test_helpers/` and `test_suite/` are at the task root and that `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, and `implementation/`.

## Step 7: Run tests and iterate — 2026-09-03T21:47:00.000Z

Clean sweep. Final state:

## Summary

**Iterations run:** 2 (each a full 8-round parallel sweep, `setsid nohup`, per-test-server isolation).

**Iteration 1:** 192/201 in all 8 rounds — 9 deterministic failures (identical set in every round, so no flakiness component).

**Tests deleted:** none. One sub-assertion removed under STEP 1c partial-coverage handling:
- `test_suite/test_11_state_machine_transitions.py::test_13_closure_after_the_window_end_retains_the_audit_fields` — dropped `assert closed["final_read_note"] == ...` (**default/field-presence silence**). PRD §3.4 says closure happens "optionally recording a `final_read_note`", but §3.4's exhaustive enumeration of a newly created order's nullable fields (`cancellation_reason`, `failure_reason`, `waiver_reason`, `readiness_snapshot`, …) omits `final_read_note`, so a faithful reader can legitimately accept the input without exposing it as an order attribute. Two divergent PRD-faithful readings exist → the sub-assertion goes; the test keeps its covered assertions (CLOSED state, both window fields retained, `confirmation_code` survival, move readiness).

**Fixes applied to `test_suite/`** (all STEP 2 test-vs-PRD faithfulness fixes; no weakening, no skips):
- `test_11_state_machine_transitions.py` (tests 10, 11, 12) — read the handoff's state from `handoff_status`, not `status`. PRD names the field `handoff_status` throughout (§2.6 rung 13, §3.5); `status` is the `IdentityVerification`/`AddressChangeFiling` field name and was mis-borrowed here.
- `test_12_calculation_constants_and_precision.py` — `_order_awaiting_a_bureau_answer` asserted `handoff["readiness_snapshot"]`; PRD §3.5 says dispatch "writes `readiness_snapshot` **on the order**", and §3.5's handoff-creation sentence enumerates only `utility_order_id`, `handoff_status`, `score`, `result`, `responded_at`, `submitted_by_user_id`. Helper now re-reads the order and asserts the frozen 40 there. (Fixed tests 07 and 08.)
- `test_16_error_catalogue_shape.py::test_08` — read the error id from `data.error_id`, matching the PRD §2.2 error envelope, instead of the non-existent `error.id`.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**
- `services/gates.py::require_credit_state` — added an `error_id` parameter (default unchanged at `ERR_ORDER_NOT_SCHEDULABLE`), so the shared credit-state guard can carry an operation-specific error id.
- `routes/orders.py::activate_order` — activation's credit gate now raises `ERR_CREDIT_NOT_CLEARED`. PRD §2.6: "Activation additionally requires the order's `credit_status` to be one of `NOT_REQUIRED`, `CLEARED` or `DEPOSIT_PAID`; when it is instead `PENDING_CHECK`, `DEPOSIT_DUE`, `DECLINED` or `VOIDED`, activation is refused with `ERR_CREDIT_NOT_CLEARED` (409)." It was incorrectly reusing rung 8's `ERR_ORDER_NOT_SCHEDULABLE`. (Fixed `test_03::test_02` and `test_07::test_04`.)

No `implementation/` check was weakened or removed; no seeded state added; storage remains in-memory dicts only.

**Final sweep (iteration 2) — passed/total per round:** all eight `results.$i.json` at 201/201, 0 failed, 0 errors, 0 skipped.

Orchestrator verification (independent of the subagent's claim): all 8 `results.*.json` exist under `workspace/implementation/`, each ~63 KB of complete JSON written at 21:46, and re-parsed here as `passed 201 / total 201 / failed 0 / errors 0 / skipped 0`. The sweep genuinely ran and left its artifacts behind.

Step 8 is therefore NOT skipped: Step 7 recorded 1 sub-assertion removal, 3 `test_suite/` fixes, and 2 `implementation/` fixes.

## Step 8: Finalize PRD — 2026-09-03T21:53:00.000Z

`PRD_FINALIZED.md` is written. Two edits; everything else in `<step_7_diff>` traced to fixture bugs or behavior PRD already determines.

## Line counts
- `PRD.md`: 507 lines; `PRD_FINALIZED.md`: 507 lines; **+0 lines (0.0%)** — both edits are in-line revisions of existing sentences (2 lines touched, ~0.4% of lines).

## Changes
- **§2.7 (out-of-ladder gate paragraph, line 160)** — revise — pinned the activation credit gate's position in the evaluation sequence: immediately after rung 8, ahead of rungs 21 (consent gate), 25 (provider status) and 37 (window timing), so a combined violation surfaces `ERR_CREDIT_NOT_CLEARED` — `implementation/routes/orders.py:261-278`.
- **§3.6 Closure (line 309)** — revise — `final_read_note` is accepted/validated as a non-empty string when present but is **not** persisted; the order resource carries no `final_read_note` attribute — `implementation/routes/orders.py:323-325` (validated and discarded), `implementation/services/mapping.py:70-85` (order creation field set).

## Per-edit pre-edit search log

**Edit 1 — activation credit gate**
- (a) Subject: the order `credit_status` gate on activation — its error id and where it sits relative to the other activation gates.
- (b) Enumerated/read: `grep require_credit_state implementation/` → exactly 3 callsites — `routes/orders.py:108` (dispatch, default `ERR_ORDER_NOT_SCHEDULABLE`), `:230` (deposit payment, default), `:262` (activation, `error_id="ERR_CREDIT_NOT_CLEARED"`); `services/gates.py:44` (default param); `grep ERR_CREDIT_NOT_CLEARED|ACTIVATION_CREDIT_OK implementation/` → only `errors.py:60`, `services/enums.py:108`, `routes/orders.py:264-267` (single site, no parallel activation endpoint); full read of `activate_order` gate order (`authenticate` → `own_if` → body → `require_move_live` (7) → `require_order_state` (8) → credit gate → `require_gate_open` (21) → `require_provider_active` (25) → window start (37)); read `gates.py` in full to confirm no other rung falls between 8 and 21 for activation.
- (c) Adjustment: scoped the sentence to activation only and named the three rungs it precedes rather than claiming a global "credit checks come first" rule — dispatch's and payment's credit-state guards keep `ERR_ORDER_NOT_SCHEDULABLE` (already covered by rung 8), so the wording deliberately says nothing about them.

**Edit 2 — `final_read_note`**
- (a) Subject: the closure request's `final_read_note` field and whether it becomes an order attribute.
- (b) Enumerated/read: `grep -rn final_read_note` across `implementation/`, `test_suite/`, `test_helpers/`, PRD → the only impl occurrence is `routes/orders.py:324` (`v.str_field(..., required=False, min_len=1, max_len=500, default=None)`, return value unused); `validators.str_field`/`_get` (absent or `null` → accepted and dropped; present non-string or empty → `ERR_INVALID_REQUEST`); `db.public()` (strips only `_`-prefixed keys, adds nothing); `services/mapping.py:70-85` order-creation field set and `services/cascades.py` order mutations (never set the key); PRD §3.5 line 275 nullable-field enumeration and §4 endpoint table (neither mentions the field).
- (c) Adjustment: said "not retained as a field of the service order resource" rather than "ignored" — the value *is* validated (an empty string or non-string still 422s), and left the 500-character cap out since the PRD states no string length caps anywhere and no impl path exposes it.

Not patched (PRD already uniquely determines them; the Step 7 items were fixture bugs): `handoff_status` naming (PRD §2.7 rung 13 / §3.6 line 295; impl uses `handoff_status` exclusively), `readiness_snapshot` living on the order and not the handoff (§3.6 line 297; impl `orders.py:138`), the `data.error_id` error envelope (§2.2; `response.py:61-68`), and activation's `ERR_CREDIT_NOT_CLEARED` id itself (§2.7 line 160 / §3.6 line 307 — the impl was the side that was wrong and Step 7 fixed it).

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` yields exactly 8 diff lines covering 2 revised lines (160 and 309) — a real, minimal, non-empty patch, not a byte-identical copy. `PRD_FINALIZED.md` still ends at the final error-table row.

## Step 9: Complete PRD — 2026-09-03T22:29:44.936Z

Run as **three sequential file-partitioned passes** over `implementation/` rather than one monolithic scan. Rationale (orchestrator decision, no user available to consult): a single subagent asked to walk 4182 lines of implementation against a 507-line PRD reliably runs out of working context and returns a PRD_COMPLETED.md that is byte-identical to its input — i.e. the scan silently never happened. Partitioning by file bounds each pass's reading load, and running the passes sequentially (never concurrently) prevents two agents from clobbering each other's edits to the same output file. Each pass was told explicitly not to re-initialize the file and not to bulk-rewrite it, only to use targeted Edit calls.

### Pass 1 — routes/config.py, routes/moves.py, routes/identity.py, routes/clock.py
Initialized `PRD_COMPLETED.md` from `PRD_FINALIZED.md`, then 27 in-paragraph edits: **4 mismatch-revisions, 23 ambiguity-pins**. 507 lines / 119,386 chars → 507 lines / 128,100 chars (+8,714).

Mismatches: §2.7 rung 6 `rev_share_pct` cap was 1.0000 but impl caps at 0.9000 (plus `monthly_placement_cap` 1–1000, `attribution_window_days` 1–90, KBA scores in the 300–850 band) — `routes/config.py:321`, `routes/identity.py:48`; §2.7 rung 21 and §3.4 "six operations" → eight (impl also gates attention clearance and move completion) — `routes/moves.py:385,425`; §3.3 KBA callback had three errors — `score` range 0–1000 → 300–850, a lapsed row settles `EXPIRED` not `FAILED`, and a pass drives `lifecycle_status` to `VERIFIED` from any state while a non-pass knocks back to `IDENTITY_FAILED` only from `IDENTITY_PENDING`/`INTAKE` — `routes/identity.py:48,63,67,70-74`.

Ambiguity pins covered: clock normalization; config-entity path misses yielding `ERR_REFERENCE_NOT_FOUND`; attention clearance also raising `ERR_FILING_NOT_SUBMITTABLE`; unconditional status-patch writes still bumping `version`; string length bounds on `email`, `city`, `unit`, `external_reference`, `override_reason`, `clearance_note`, `cancellation_reason`; marketing-preference writes applied unconditionally; `required_account_fields` stored in submitted order and not deduplicated; territory default-row conflict semantics and unscoped listing; nulls and `version` 1 at intake even when flagged `SUSPECTED`; `RESCORE` re-running the first pass only; the self-merge bar firing whenever `survivor_move_id` is supplied; attempt-opening lifecycle set; the 72h `expires_at` minted uniformly; mapping's `utility_types` dedup, `include_stop_orders` default, whole-planned-set coverage test, destination-only `unmapped_utility_types`, and returning the updated move; consent evaluation's resident-wide sweep vs the move-scoped identity sweep; readiness `variant` fallback and purity; the pinned three-remedy clearance order; completion's gate order; and unscoped move/verification listings.

### Pass 2 — routes/orders.py, routes/filings.py, routes/consents.py, routes/placements.py
25 in-paragraph edits: **4 mismatch-revisions, 21 ambiguity-pins**. 128,100 → 136,123 chars (+8,023), still 507 lines.

Mismatches: §3.5 scheduling claimed it enforces the 50000-cent deposit ceiling but impl never reads `deposit_amount_cents` there — `routes/orders.py:61-94`; §3.6 `DECLINED` branch (provision moves from `DRAFT` **or** `SCHEDULED`, park hop fires even when no order was failed, credit dimension is *not* voided) — `routes/orders.py:199-207`, `services/cascades.py:83-91`; §3.6 provision failure said `SCHEDULED` only but impl accepts `DRAFT` too — `routes/orders.py:299,303`; §3.7 withdrawal said `cancellation_reason` optional but impl requires it — `routes/filings.py:232`.

Also pinned: rung 7's exact applicability set (which child writes gate on the parent move's `lifecycle_status` and which do not); rung 8's per-operation order-state sets; consent `move_id` miss vs wrong-owner distinction; that **`PARTNER_MARKETING` has no restoration path**; a `NONE`-policy order landing `DEPOSIT_DUE` at 0 cents settled by a 0-cent payment; the monthly cap counting every placement regardless of status; the feed-source cut taken even from a `SUSPENDED` feed; settlement's 0 → `ERR_SETTLEMENT_AMOUNT_INVALID` vs negative → `ERR_INVALID_REQUEST` with both delta entries posting even at 0; and that **cascade-cancelled filings keep `cancellation_reason` null** while sibling orders carry one.

### Pass 3 — app.py, db.py, errors.py, response.py, middleware.py, validators.py, services/*.py
19 in-paragraph edits across 18 lines: **7 mismatch-revisions, 12 ambiguity-pins**. 136,123 → 142,002 chars (+5,879), still 507 lines.

Mismatches: §2.7 rung 16 also requires the move's *latest* verification to stand at `PASSED`, not merely a non-null `verified_at` — `gates.py:93-99`; §2.9's flat "every row a hop touches has its `version` incremented" is false — derived-field commits bump only when one of the tracked move fields changed, with duplicate resolution, attention clearance, completion, cancellation and placement creation forcing it — `derive.py:17-46`, `revenue.py:62-64`; §3.1 `full_name` is trimmed + case-folded only, not whitespace-collapsing, and `line1` is lower-cased verbatim into the hash — `duplicates.py:14-15,40-50`; §3.2's "candidate existed before" is `(created_at, write sequence)` — `db.py:122-129`; §3.4's consent gate is per-scope (a scope blocks only when a `REVOKED`/`EXPIRED` record exists *and* no record in that scope is still `GRANTED`) and the revocation hop recomputes the gate rather than blanket-suspending, also clearing `requested_service_date` — `derive.py:75-88`, `cascades.py:33-44,130-160`.

Ambiguity pins: whitespace-only headers counting as absent; `api_request_id` shape; pagination `meta` on list responses only; `ERR_INVALID_REQUEST` for bad `limit`/`offset` with leading `+` tolerated and empty falling back to default; the same-`created_at` write-sequence tie-break (never serialized) settling both ordering and every "latest child" selection; filter stringification semantics; rung 6's body-parsing semantics (absent body = `{}`, explicit `null` = absent, undeclared fields ignored, strict int typing); >4 decimal places rounded half-up and decimals travelling as JSON numbers without trailing zeros; `account_data` emptiness semantics; and the unconditional `PARTNER_MARKETING` re-stamp.

Pass 3's verdicts on the 7 items forwarded from passes 1–2: items 1, 2, 3, 4 and 7 edited; item 5 (`authenticate` always granting `PlatformAdmin`) needed no change — §2.1 already states it and all 64 §4 rows already list `PlatformAdmin`; item 6 (`revenue.ledger_balance`) needed no change — unexposed dead code, and §2.9 frames the ledger net as an invariant rather than a field.

### Orchestrator-applied closing edit (2 edits, +3 lines)
Pass 3 flagged that `implementation/app.py:48-74` also emits `ERR_NOT_FOUND` (404), `ERR_METHOD_NOT_ALLOWED` (405) and `ERR_INTERNAL` (500), none of which appeared anywhere in the PRD — but it declined to act because my pass-3 prompt asked it to verify the §5 table still held 58 rows. That instruction was an anti-truncation integrity guard, not a cap on legitimate pins, and leaving the gap would violate Step 9's zero-residual-silence mandate, so I closed it myself: an inline insert in §2.6 distinguishing an unmatched route (`ERR_NOT_FOUND`) from an entity-specific miss, naming the 405 and 500 cases and pointing at the §2.2 envelope; plus three rows appended to the §5 catalogue. Verified against `app.py` that all three ids and statuses match exactly and that no other undocumented code is emitted.

### Final state
- `PRD_COMPLETED.md`: **510 lines / 142,627 chars** (source `PRD_FINALIZED.md` was 507 lines / 119,386 chars — char-delta **+23,241**, +19.5%).
- Totals across all three passes plus the closing edit: **15 mismatch-revisions, 56 ambiguity-pins, 73 edits**; 68 lines differ from `PRD_FINALIZED.md`, and the only line-count growth is the 3 appended catalogue rows.
- Integrity verified by the orchestrator: file is NOT byte-identical to its source (the known silent-failure mode did not occur); §4 endpoint table still has 64 method rows; §5 error table now has 61 `ERR_` rows (58 original + 3 added); the file ends at a genuine table boundary (`| \`ERR_INTERNAL\` | 500 |`).
- No implementation or test file was modified after the green sweep at 21:46 (verified by mtime), so the 8-round 201/201 result still describes the current code. Step 9 touched only `PRD_COMPLETED.md`.

Pipeline complete: Steps 1–9 all executed, `workspace/PRD_COMPLETED.md` written.
