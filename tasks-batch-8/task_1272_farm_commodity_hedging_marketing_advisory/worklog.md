# Worklog — task_1272_farm_commodity_hedging_marketing_advisory

## Step 1: Create task directory — 2026-08-12T14:43:00.000Z

Pre-assigned output folder `tasks/task_1272_farm_commodity_hedging_marketing_advisory` with `workspace/` subdirectory already exists; Step 1 auto-index scan skipped per instructions. Treating Step 1 as done.

## Step 2: Generate scaffold — 2026-08-12T15:46:00.000Z

Scaffold generation complete. All three artifacts are written, parse cleanly, and pass the skill's mechanical linter with a clean verdict.

## Deliverables (all under /home/ubuntu/github/CodingPRD/tasks/task_1272_farm_commodity_hedging_marketing_advisory/)

**SCAFFOLD.yaml** — 90,159 bytes, 1,165 lines. YAML parses; top-level keys: `scenario, domain_name, api_prefix, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, response_envelope, endpoints, errors, roles` (no `scaffold_difficulty_design` / `scaffold_corner_design` keys, per the file-split rule).
- §1.1: 14 entities (GrowerOperation, ProductionBaseline, InsurancePolicy, MarketingPlan, PriceTarget, HedgeRecommendation, BrokeragePosition, MarginAccount, Buyer, SalesContract, DeliveryTicket, StorageLot, AdvisoryAgreement, MarketTick), flat topology with canonical `FK -> Entity.id` descriptions; every FK has a reverse-reachability GET.
- §1.2: 12 state machines — cycles (MarketingPlan ACTIVE↔SUSPENDED, MarginAccount FUNDED↔CALL_OUTSTANDING↔RESTRICTED, Buyer APPROVED↔SUSPENDED), two independent state dimensions on SalesContract (pricing_status × fulfillment_status), TTL expiry, auto-close cascades.
- §1.2.1: 2 OCC concurrency rules (`plan-amend-stale-version`, `baseline-create-stale-operation`), both 412/ERR_STALE_VERSION with endpoint input+version-bump linkage.
- §1.3: 10 calculations — 3 dual-variant (expected bushels APH vs TREND; benchmark marketing-year vs harvest-window; advisory fee PER_BUSHEL vs FLAT), combinatorial modes (a) coverage cap with nested min + risk-profile branch, (b) pinned per-ticket-then-sum settlement rounding, (c) forced-liquidation pinned evaluation order; plus insurance indemnity, margin accounting, storage breakeven (part-month ceil), cash-flow bucketing.
- §1.4: 11 ordered validations (auth → role/ownership → schema → existence → OCC → state → safety/compliance → referential → temporal → constraint → fiscal).
- §1.5: 72 endpoints including the `/_clock/set_current_utc` test-driving endpoint with the mandated `2026-05-01T00:00:00Z` startup default; §1.6: 28 error codes, all referenced; §1.7: 4 roles (PlatformAdmin/CommodityAdvisor opaque, Grower `entity_backed:GrowerOperation`, ComplianceOfficer) with segregation-of-duties (submitter may not certify own agreement).

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 83,637 bytes, 757 lines. Single top key `scaffold_difficulty_design`; 9 rule groups, 20 instances (dual_variant_calc ×3, combinatorial_formula ×3 across modes a/b/c, all other rules ×2). Every instance has structured `setup_api_calls`/`trigger` chains with closed `${var}` placeholders and pre-computed literal asserts (verified by executing the formulas: e.g. expected bushels 20000 vs 20500; benchmark 4.4750/331 bps vs 4.7000/−163 bps; fee 391.00 vs 5000.00; settlement 89052.20 vs sum-then-round 89052.21; liquidation spares position B with cash 14000.00; margin call cure at exactly 15000.00).

**SCAFFOLD_CORNER_DESIGN.yaml** — 119,777 bytes, 1,088 lines. Single top key `scaffold_corner_design`; 9 sections matching the claim-extraction guide taxonomy; 49 active instances + 8 `excluded_because` stubs (all stub references resolve to real §1.8 instance names; zero duplicate names across the union of both design files; all `grounds` references resolve to declared §1.1–§1.7 elements).

## Verification
- `scaffold_lint.py` final verdict, verbatim: **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (72 endpoints, 14 entities, 20 + 49 instances, 827 calls scanned; two initial FK_REVERSE_UNREACHABLE violations on `baseline_id` were fixed by adding `baseline_id?` filters to the policy/plan list endpoints.)
- Forbidden concurrency vocabulary scan: no hits.
- All numeric asserts were computed with Python (Decimal, round-half-up) before being pinned.

Design notes: "harder than expert" was carried by density rather than bloat — two OCC write races, three dual-variant calculations in different entity domains, a depth-3 tick→target→recommendation→plan cascade with headroom-reservation semantics, a depth-3 confirm→delivered→plan-recompute→auto-close cascade, half-open vs buffer-gap interval semantics, per-line-then-sum rounding pinned against the 1-cent-divergent alternative, and a logical clock driving TTL/window rules deterministically. The pre-existing `worklog.md` and `workspace/` in that directory were left untouched (not created by this run).

Orchestrator disk verification: all three files exist (90,159 / 119,777 / 83,637 bytes) and each parses as YAML with expected top-level keys.

## Step 3: Copy shared files — 2026-08-12T15:48:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1272_farm_commodity_hedging_marketing_advisory/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-12T15:58:00.000Z

The PRD is complete and verified. Here is the verbatim summary:

## Generation Report

**File path:** `/home/ubuntu/github/CodingPRD/tasks/task_1272_farm_commodity_hedging_marketing_advisory/workspace/PRD.md`
**Size:** 65,340 bytes
**Line count:** 346 lines

**Section coverage (scaffold → prose):**
- §1 Introduction — `scenario`, logical-clock semantics, startup default `2026-05-01T00:00:00Z`, `to_iso8601` / `current_utc` test-driving capability
- §2.1 — `roles[]` (all 4 roles with exact spelling, identity translation: Grower entity-backed via `GrowerOperation.id`, three opaque roles), `ERR_UNAUTHENTICATED` / `ERR_FORBIDDEN_ROLE` / `ERR_RESOURCE_NOT_OWNED`
- §2.2 — `response_envelope` emitted byte-identical to the canonical block (verified with difflib: identical)
- §2.3 — pagination defaults (`limit` 10, min 1, max 100, `offset` 0), `created_at` ascending sort, `meta` fields
- §2.4 — common resource properties; `MarketTick` (`common_fields: false`) explicitly noted as lacking `updated_at` and `version`
- §2.5 — both `concurrency_rules` (`plan-amend-stale-version`, `baseline-create-stale-operation`) with `expected_marketing_plan_version` / `expected_operation_version`, `ERR_STALE_VERSION` (412), and the no-other-endpoints clause
- §2.6 — all 11 `validations[]` priorities rendered as an explicit ordered cascade
- §2.7 — precision rules (2dp half-up dollars, 3dp net bushels, 4dp prices, integer-floored bushel pools) plus coverage-cap rule with `RISK_COVERAGE_CAP` constants (0.60/0.80/1.00)
- §2.8 — temporal rules: half-open delivery windows, 7-day storage bin buffer, logical clock
- §2.9 — disclosure sub-state machine, version pinning, governing-agreement tie-break (most recently activated, greatest `created_at`), segregation of duties
- §2.10 — margin accounting: IM/MM rates (0.30 / 0.22, LONG_PUT premium+0.05), equity definition, call-amount freeze
- §2.11 — price feed, SETTLEMENT-only marking, latest-settlement selection (greatest `price_date`, tie-break `created_at` ascending)
- §2.12 — cascade discipline and version/`updated_at` semantics on derived-field recomputation
- §3.1–3.11 — all 13 entities' lifecycles, all 12 state machines' transitions (from/to, actors, preconditions with error IDs, side effects), all 10 calculations (both yield variants, both fee variants, both benchmark variants, both PnL forms, pinned liquidation order, pinned per-line rounding order), all endpoint side effects
- §4 — 72 endpoints in a 4-column table (Method, Path, Description, Authorized Role), roles verified cell-by-cell against scaffold: zero mismatches
- §5 — 28 error codes in a 2-column table with HTTP statuses matching scaffold

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 95 required, 95 present, 0 missing
- endpoints[].request_body: 56 required, 56 present, 0 missing
- endpoints[].query_params: 19 required, 19 present, 0 missing
- endpoints[].path_params: 13 required, 13 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 11 checked, 11 expressed in prose (ordered cascade in §2.6), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write path + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 39 checked across 12 machines, 39 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed (constants, precision, variants, pinned orders), 0 missing
- validations[] conditions: 11 checked, 11 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 72 endpoints checked, all side effects expressed in §3 narratives, 0 missing
- entities[].fields[] structured content: 95 fields checked (defaults, enums, conditional requirements, computed semantics), 0 missing
- sibling-branch symmetry: 24 paired groups checked, 24 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 677
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Confirmation:** Every endpoint (72/72), every error code (28/28), every role (4/4), every state machine (12/12, all transitions and state enum values), and every calculation (10/10, including all dual variants, constants, precision rules, and pinned evaluation orders) from SCAFFOLD.yaml is covered in the PRD prose. §2.2 is byte-identical to the canonical response-structure block. No fuzzy/approximating words and no pseudocode operators appear in prose (machine-scanned). The difficulty-design and corner-design files were not opened, read, or referenced at any point.

Orchestrator disk verification: PRD.md exists (65,340 bytes, 346 lines).

## Step 5: Generate unit tests — 2026-08-12T16:15:00.000Z

All checks pass. Final verbatim summary:

---

## Generation Summary — task_1272_farm_commodity_hedging_marketing_advisory

### Files written

**test_helpers/ (9 modules):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1272_farm_commodity_hedging_marketing_advisory/test_helpers/__init__.py` — barrel export (framework generics + PRD-specific)
- `types.py` — 16 status/role enums + 15 entity TypedDicts (MarketTick correctly omits `updated_at`/`version`, common_fields:false)
- `api_client.py` — `ApiClient(GenericApiClient)` with 49 endpoint methods covering every PRD §4 row incl. `_clock/set_current_utc`
- `api_errors.py` — 28 `ApiErrorId` values + HTTP map registered via `set_error_http_status_map`
- `constants.py` — thresholds (RISK_TREND_FACTOR, RISK_COVERAGE_CAP, IM/MM rates, TTL 5d, moisture 15.0/0.012, tolerance 1.02, 7-day buffer) + `MISSING_UUID`
- `factories.py` — 19 payload factories (input fields only)
- `test_users.py` — `TEST_USERS` shared constants + `make_grower_headers` (entity-backed identity threading) + per-role builders
- `assertions.py` — 15 per-entity `assert_*` functions (UUID/ISO-8601 common-field checks via framework)
- `fixtures.py` — composite helpers: `create_operation`, `create_baseline_for` (OCC version re-read), `create_certified_baseline`, `activate_agreement`, `create_active_agreement`, `create_approved_buyer`, `setup_operation_with_active_plan`, `setup_active_plan_with_buyer`, `create_flat_contract`, `create_confirmed_delivery`, `create_accepted_recommendation`, `create_open_position`, `setup_margin_account`, `record_settlement_tick`/`record_quote_tick`, `set_logical_clock`, `setup_account_in_margin_call`

**test_suite/ (10 files):** `conftest.py` + `test_01_operation_onboarding.py`, `test_02_marketing_plan_lifecycle.py`, `test_03_tick_cascade_and_targets.py`, `test_04_coverage_cap_and_acceptance.py`, `test_05_sales_contracts_and_delivery.py`, `test_06_margin_and_liquidation.py`, `test_07_insurance_and_oversold.py`, `test_08_agreements_and_fees.py`, `test_09_reports_storage_pagination.py`

### Counts
- **90 test functions total**
- **Queue A (Difficulty): 40 tests** — all 20 instances covered with exactly 2 tests each (≥2 target met)
- **Queue B (Corner): 50 tests** — all 49 non-stub instances covered with ≥1 test (`over_sold_flag_blocks_then_clears_on_cancel` has 2)
- **8 `excluded_because` stubs NOT translated** (7 error stubs + `dual_variant_layer_stub`); all cross-references verified to resolve to real §1.8 instances

### Skipped instances
None. All 20 difficulty and 49 non-stub corner instances passed the PRD-first two-condition filter (every asserted rule — including both priority-ordering pairs, §2.6 steps 6-vs-11 and 7-vs-8 — is verbatim-stated in PRD prose with uniquely-derived outcomes). Zero instances skipped; no `pytest.mark.skip`/`xfail` anywhere.

### Verification results
- **Lint:** `python3 -m py_compile` on all 20 .py files (test_helpers + test_suite) — OK; `import test_helpers` — OK
- **Design-tag audit:** every one of the 90 tests carries exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line as the final docstring line; all tags resolve to real instances in the source yamls; no tag points at an excluded stub
- **PRD verbatim-citation pass:** 137 quoted fragments extracted from docstrings — all 137 found literally in `workspace/PRD.md` (whitespace-normalized grep); 0 failures
- **Numeric audit:** all pre-computed assertion literals from the design indices re-verified independently (WAP 4.6233, bps 331/−163, cap 14000, ticket values 44731.08/44321.12, settled 89052.20, liquidation −6000/−12000/−8000, call amounts 5000/10000/4500, breakeven 5/7500/5500/4.66, guarantee 150000, indemnity 48000/0, penalty 5000, fee 391/5000, tolerance 10200/10201)
- **Clock hygiene:** only two tests advance the logical clock, both single-shot terminal moves at the end of setup (TTL expiry, contract default) — no time-dependent rule is exercised after a clock mutation in any test

## Step 6: Generate implementation — 2026-08-12T16:15:30.000Z

All verification checks pass. Implementation complete.

## Summary

**File list** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1272_farm_commodity_hedging_marketing_advisory/workspace/implementation/`):

```
./app.py                                  2071 bytes
./db.py                                   1459 bytes
./errors.py                               2162 bytes
./helpers.py                              7707 bytes
./middleware.py                           1313 bytes
./requirements.txt                          16 bytes
./response.py                             1356 bytes
./routes/agreements.py                   10585 bytes
./routes/baselines.py                     5056 bytes
./routes/buyers_contracts.py             15480 bytes
./routes/insurance.py                     5814 bytes
./routes/operations.py                    9470 bytes
./routes/plans.py                         8998 bytes
./routes/positions_margin.py             10551 bytes
./routes/recommendations.py              10747 bytes
./routes/storage.py                       6699 bytes
./routes/targets_ticks.py                 5481 bytes
./routes/tickets.py                       8567 bytes
./serializers.py                          2282 bytes
./services.py                            13179 bytes
./start.sh                                 396 bytes (executable)
```

**Boot test**: `bash start.sh` boots Flask on `0.0.0.0:$PORT` in the foreground via `exec`. Verified end-to-end: 401 probe on POST `/advisory/operations` without headers returns `ERR_UNAUTHENTICATED`; 404 probe on missing resource returns `ERR_NOT_FOUND`. Logical clock starts at `2026-05-01T00:00:00Z` and is settable via `POST /advisory/_clock/set_current_utc`.

**Route diff**: `declared=72 registered=72 missing=0 extra=0` — **ZERO MISMATCHES** against SCAFFOLD.yaml §1.5 endpoint table (the auto-generated `GET /static/<path:filename>` Flask route was excluded from the count).

**py_compile**: all 18 `.py` files compile cleanly.

**Design decisions where PRD left ambiguity**:
1. **`version` discipline on AdvisoryAgreement**: PRD §3.10 states "only submit and PUT amendment increment version" — so `deliver-disclosure`, `acknowledge-disclosure`, `sign`, and `certify-compliance` refresh `updated_at` only (via `touch_no_version`), while `submit` and PUT amendment use full `touch()`.
2. **Auto-minted recommendation `instrument`**: scaffold/PRD do not pin the instrument when a PriceTarget trigger mints a HedgeRecommendation; I default to `FUTURES_SHORT` (no strike/premium) since the target carries no strike information.
3. **`plan_id` on BrokeragePosition**: scaffold lists `recommendation_id`, `operation_id`, `margin_account_id` but omits `plan_id`; I added it because the plan's `hedged_bushels` recompute needs to find OPEN positions "for this plan" (PRD §3.3) and the recommendation's plan_id is the only path.
4. **Coverage cap re-check on contract creation**: PRD §3.7 says FLAT_PRICE creation enforces the cap, HTA/BASIS enforce it at fix-price. I check `hedged + priced + bushels > cap` at those exact points.
5. **Over-sold evaluation**: PRD §3.2 anchors the tripwire to "settled insurance claim" — `evaluate_over_sold` uses the most recent `CLAIM_SETTLED` policy's `actual_harvested_bushels` as marketable; with no settled claim, the flag stays as-is.
6. **404 handler returns `ERR_NOT_FOUND`** for both unknown paths and method-not-allowed (405 remapped to 404) so the error envelope stays uniform per the scaffold's error catalog which has no 405 entry.
7. **Storage bin buffer scope**: applies to same `bin_id` regardless of `operation_id` (PRD §2.8 says "the same bin" without operation qualifier; bin codes are elevator-scoped).
8. **`billable_bushels` in fee-statement response**: returned as a float (3dp sum of net_bushels), not integer — PRD says "the sum of net_bushels" and net_bushels is 3dp.

Orchestrator disk verification: test_helpers/ (9 modules), test_suite/ (conftest + 9 test files, 90 test functions), workspace/implementation/ (18 .py files + start.sh + requirements.txt) all present; `python3 -m py_compile` over all sources passes.

## Step 7: Run tests and iterate — 2026-08-12T16:40:00.000Z

# Summary

**Iterations run:** 2 (iteration 1: 84–85/90 per round with a consistent 5-test failure union plus load-related server-restart flakes; iteration 2: 90/90 in all 8 rounds, zero flakes).

**Tests deleted:** none — every failing test traced to verbatim PRD prose with uniquely derivable outcomes.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:** none.

**Fixes applied to `implementation/`** (3 files, all STEP 3 implementation bugs):

1. `/home/ubuntu/github/CodingPRD/tasks/task_1272_farm_commodity_hedging_marketing_advisory/workspace/implementation/routes/plans.py` — `activate_plan`: removed a standalone `touch(p)` before `recompute_plan_counters(p)` (which itself touches). The double-touch bumped plan version by 2 on activation (2→4). PRD §3.3 pins one increment per request ("A successful amendment recomputes `coverage_cap_bushels` and increments the plan's `version` by one"); §2.4's "recompute is itself a mutation" clause covers cascade-triggered recomputes on *other* entities, not double-counting within one request. Fixed `test_version_increments_on_each_mutation`.

2. `/home/ubuntu/github/CodingPRD/tasks/task_1272_farm_commodity_hedging_marketing_advisory/workspace/implementation/serializers.py` — added `billable_bushels_accrued` to `AGREEMENT_DECIMALS`. After ticket confirmation the field held a `Decimal` and serialized as the string `'4000.000'`; PRD §3.10 defines it as a numeric cumulative count of net bushels. Fixed `test_void_confirmed_ticket_compensates_fully`.

3. `/home/ubuntu/github/CodingPRD/tasks/task_1272_farm_commodity_hedging_marketing_advisory/workspace/implementation/routes/agreements.py` — `create_agreement`: removed the "flat_annual_fee forbidden for PER_BUSHEL" / "rate_per_bushel forbidden for FLAT_ANNUAL" cross-field rejections. PRD §3.10 states only "required for" rules for the conditional fee fields (contrast §3.7 contracts, where PRD explicitly says "forbids the other pricing fields"); the check traced to neither PRD nor scaffold and was rejecting PRD-legal setup payloads. Fixed `test_sign_without_acknowledgment_rejected`, `test_amendment_marks_acknowledgment_stale`, `test_certify_with_same_user_returns_forbidden`.

**Note on iteration-1 ERRORs:** the sporadic "API server could not be restarted" errors (different tests in rounds 1/3/5/6/7/8) were 8-way-parallel load artifacts, not implementation or test defects — they did not recur in iteration 2, and every affected test passed in the rounds where the server restarted normally.

Orchestrator disk verification: all 8 `workspace/implementation/results.{1..8}.json` files present; every round reports passed=90 total=90 failed=0 errors=0.

## Step 8: Finalize PRD — 2026-08-12T16:48:00.000Z

PRD_FINALIZED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1272_farm_commodity_hedging_marketing_advisory/workspace/PRD_FINALIZED.md`. All three Step 7 implementation fixes traced to PRD-silence items; all three were patched. No test-deletion or test-helper items existed to trace.

## Line counts

- `PRD.md`: 346 lines; `PRD_FINALIZED.md`: 346 lines — 0% line-count delta (three in-place sentence revisions, no sections added or removed).

## Changes

- **§3.3 — revise** — Added "The whole activation — the status transition, the snapshot freeze, the coverage-cap computation, and the accompanying recomputation of the plan's derived counters — is a single mutation of the plan: its `version` increments by exactly one and `updated_at` refreshes once." — `implementation/routes/plans.py:146-167` (`activate_plan` performs exactly one touch via `recompute_plan_counters`).
- **§3.10 — revise** — Recast the conditional fee fields as "presence requirements only … no cross-field prohibition applies here: supplying the other fee type's field alongside the required one is accepted and stored without error, and a field that does not match the agreement's `fee_type` simply plays no role in the fee-statement computation." — `implementation/routes/agreements.py:31-42, 52-54` (`create_agreement` enforces only required-for rules and stores both fields).
- **§3.10 — revise** — `billable_bushels_accrued` now described as "a cumulative total of the net bushels … a numeric quantity carried at net-bushel precision and, like the agreement's other decimal-valued fields, serialized in responses as a JSON number, never as a string." — `implementation/serializers.py:83-85` (`AGREEMENT_DECIMALS` includes `billable_bushels_accrued`, serialized via `to_float`).

## Per-edit pre-edit search log

**Edit 1 (§3.10 fee conditional fields)**
- (a) Subject: validation and use of `rate_per_bushel` / `flat_annual_fee` / `annual_cap_dollars` on `AdvisoryAgreement`.
- (b) Enumerated paths: grep for all three field names across `implementation/`; read `routes/agreements.py` in full — `create_agreement` (lines 31-42: required-for checks only, no cross-field rejection), `amend_agreement` (lines 165-190: accepts optional updates to any of the three regardless of `fee_type`, no cross-checks), `fee_statement` (lines 231-240: only the `fee_type`-matching field enters the fee; `annual_cap_dollars` applies to both variants); `serializers.py:83` (all three serialize as JSON numbers). Also contrasted §3.7 contract pricing fields, which PRD explicitly marks as "forbids the other pricing fields" — the edit cites that contrast rather than contradicting it.
- (c) Wording adjustment: explicitly said "accepted and stored" plus "plays no role in the fee-statement computation" so the sentence covers the amendment and fee-statement paths, not just creation; avoided any claim that the inapplicable field is nulled or hidden (impl stores and returns it).

**Edit 2 (§3.3 activation version increment)**
- (a) Subject: plan `version` increments on activation.
- (b) Enumerated paths: grep of every `touch(` callsite in `routes/` and `services.py`. Plan-version paths: `create_plan` (version=1), `amend_plan` (+1, already pinned by PRD), `activate_plan` (+1 via the single touch inside `recompute_plan_counters`), `suspend_plan`/`resume_plan`/`close_plan` (+1 each), ticket confirm/void → `recompute_plan_counters` (+1 per request, plus a second touch when auto-close fires), tick cascade `fire_price_targets` (one recompute per fired target, so a plan can gain multiple versions in one tick). Critically, `services.py:336-348` (`remark_positions`) touches the *margin account* twice in one tick request (recompute + call issuance), so a universal "one request = one increment" claim would be a new mismatch.
- (c) Wording adjustment: scoped the sentence strictly to activation ("The whole activation … is a single mutation of the plan") instead of a general per-request rule, leaving §2.4/§2.12 verbatim so cascade multi-touches (tick re-marks, confirm-then-auto-close) remain consistent.

**Edit 3 (§3.10 `billable_bushels_accrued` serialization)**
- (a) Subject: JSON representation and precision of `billable_bushels_accrued`.
- (b) Enumerated paths: `serializers.py:83-85` (`ser_agreement` applies `AGREEMENT_DECIMALS` → `to_float` on every agreement response: create/get/list/submit/deliver/acknowledge/sign/amend/certify — all route through `ser_agreement`, confirmed by reading `agreements.py`); mutation sites `routes/tickets.py:166, 200` (Decimal add/subtract of 3-decimal `net_bushels`); initial value `0` at `agreements.py:55` (serialized as `0.0`). Verified the fee-statement's separate `billable_bushels` computed-read field (`agreements.py:220-247`) is unaffected by wording about the resource field.
- (c) Wording adjustment: replaced "count" (which could imply integer) with "cumulative total … carried at net-bushel precision", and pinned "JSON number, never as a string" narrowly to this field with a same-convention reference to the agreement's other decimal fields, avoiding a global serialization claim the PRD does not otherwise make.

Orchestrator disk verification: PRD_FINALIZED.md exists alongside PRD.md (both 346 lines).

## Step 9: Complete PRD — 2026-08-12T17:00:00.000Z

Done. PRD_COMPLETED.md written at `/home/ubuntu/github/CodingPRD/tasks/task_1272_farm_commodity_hedging_marketing_advisory/workspace/PRD_COMPLETED.md`.

## Summary

**Size**: PRD_FINALIZED.md 346 lines / 66,186 chars → PRD_COMPLETED.md 346 lines / 71,025 chars (char-delta +4,839; 27 paragraphs touched, all in-paragraph edits, no new sections).

**Counts**: 25 ambiguity-pins, 2 mismatch-revisions.

**Changes** (section — insert|revise — ambiguity|mismatch — what — impl ref):

- §2.3 — insert — ambiguity — `has_more` = `offset + limit < total_count`; non-integer/out-of-range pagination params → `ERR_VALIDATION`; optional exact-match filter query params (`operation_id`, `status`, `plan_id`, etc.); Grower list responses implicitly scoped to own operation — response.py:34; helpers.py:176-192; list routes throughout
- §2.9 — insert — ambiguity — NONE/REQUIRED/DELIVERED → `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`, STALE/stale pin → `ERR_DISCLOSURE_STALE`, missing ACTIVE governing agreement → `ERR_AGREEMENT_NOT_ACTIVE` surfacing before disclosure sub-checks — routes/plans.py:130-143, routes/buyers_contracts.py:179-186
- §2.11 — insert — ambiguity — forced liquidation added to settlement-mark-requiring operations (`ERR_NO_SETTLEMENT_PRICE` when any OPEN position lacks a mark) — routes/positions_margin.py:210-214
- §3.1 — insert — ambiguity — `crop_year` integer; `planted_acres` positive integer; both yields positive — routes/operations.py:32, routes/baselines.py:31-33
- §3.2 — insert — ambiguity — `projected_price` positive; baseline must belong to the operation (`ERR_VALIDATION`) — routes/insurance.py:42, 50-51
- §3.2 — insert — ambiguity — "marketable production" = `actual_harvested_bushels` of most recently created `CLAIM_SETTLED` policy; no settled claim → flag unchanged — services.py:185-209
- §3.3 — revise — mismatch — activation precondition order changed from baseline-first to impl order: DRAFT state → agreement ACTIVE → disclosure ACKNOWLEDGED → pin current → baseline CERTIFIED — routes/plans.py:146-158
- §3.3 — revise — ambiguity — resume re-runs full governing-agreement gate set (`ERR_AGREEMENT_NOT_ACTIVE` / `ERR_DISCLOSURE_NOT_ACKNOWLEDGED` / `ERR_DISCLOSURE_STALE`), not only stale — routes/plans.py:182-192
- §3.3 — insert — ambiguity — target creation gates only on plan existence (no plan-status gate); `target_price` positive, `increment_bushels` positive integer — routes/targets_ticks.py:32-36
- §3.4 — insert — ambiguity — tick `price` must be positive — routes/targets_ticks.py:115
- §3.4 — insert — ambiguity — auto-minted recommendation is always `FUTURES_SHORT` with null strike/premium/rationale/`created_by_user_id` — services.py:266-283
- §3.4 — revise — ambiguity — expiry moves originating target from `TRIGGERED` to `LAPSED` — services.py:304-309
- §3.5 — insert — ambiguity — supplying `strike_price`/`premium_per_bushel` on `FUTURES_SHORT` is `ERR_VALIDATION` — routes/recommendations.py:45-48
- §3.5 — revise — ambiguity — rejection moves originating target from `TRIGGERED` to `LAPSED` — routes/recommendations.py:153-157
- §3.5 — insert — ambiguity — missing margin account at execution → `ERR_NOT_FOUND`; execute returns minted position with 200 OK — routes/recommendations.py:178-179, 256
- §3.6 — insert — ambiguity — `initial_funding` non-negative (zero accepted); second account for an operation → `ERR_INVALID_STATE` — routes/positions_margin.py:113, 121-122
- §3.7 — revise — mismatch — contract-creation gate order: disclosure-compliance check moved before buyer-`APPROVED` check (per §2.6 and impl) — routes/buyers_contracts.py:174-190
- §3.7 — insert — ambiguity — non-inverted window (`start` strictly before `end`, else `ERR_VALIDATION`); plan must belong to `operation_id` (`ERR_VALIDATION`) — routes/buyers_contracts.py:155-156, 168-169
- §3.7 — insert — ambiguity — `fixation_price` positive; fix-price on DELIVERED/CANCELLED/DEFAULTED contract → `ERR_INVALID_STATE` — routes/buyers_contracts.py:291-294
- §3.8 — insert — ambiguity — `gross_bushels` positive integer; recording against CANCELLED/DEFAULTED contract → `ERR_INVALID_STATE` — routes/tickets.py:38, 49-50
- §3.8 — insert — ambiguity — confirmation requires ticket `RECORDED` (else `ERR_INVALID_STATE`); agreement accrual only when a governing ACTIVE agreement exists — routes/tickets.py:131-132, 164-167
- §3.9 — insert — ambiguity — `planned_end_date` ≥ `start_date` (equality allowed); `cost_per_bushel_month`/`annual_interest_rate` non-negative; bin buffer matched on `bin_id` alone across operations — routes/storage.py:44-47, 56-74
- §3.10 — insert — ambiguity — certify-compliance has no agreement-status gate; segregation check applies only once `submitted_by_user_id` is recorded — routes/agreements.py:194-204
- §3.10 — insert — ambiguity — fee-statement `period_start`/`period_end` are required query params, missing/unparseable → `ERR_VALIDATION` — routes/agreements.py:213-218
- §3.11 — insert — ambiguity — invalid `benchmark_method` → `ERR_VALIDATION` — routes/operations.py:74-76
- §3.11 — insert — ambiguity — `through_date` truncates at its month inclusive; only months with ≥1 contributing event appear as buckets; empty horizon → empty buckets + zero totals; bucket fields `month`/`inflow`/`outflow`/`net_cash_flow`/`cumulative_cash_flow` — routes/operations.py:207-243
- §5 — insert — ambiguity — unknown path/unsupported method → `ERR_NOT_FOUND` (404); unexpected failure → `ERR_INTERNAL` (500) — app.py:30-43

No remaining PRD-vs-implementation divergence was found in formulas, state machines, error codes, or check ordering beyond the two ordering mismatches above.
