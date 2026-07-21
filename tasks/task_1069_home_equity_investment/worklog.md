# Worklog — task_1069_home_equity_investment

Scenario: Home-Equity Investment (Point/Hometap style): application & AVM/appraisal, investment offer & option term, lien & title, no-monthly-payment structure, settlement (sale/buyout) & appreciation-share calc, servicing & maintenance covenant, dispute, exit
Difficulty: Expert

## Step 1: Task directory — 2026-07-21T10:57:33.000Z

Directory tasks/task_1069_home_equity_investment/ and workspace/ pre-assigned (already existed). No index scan performed. INSTRUCTION.md present at repo root.

## Step 2: Scaffold generation — 2026-07-21T11:29:00.000Z

All three files complete, structurally correct, pass scaffold linter cleanly.

Scaffold size:
- Entities: 13 (Fund, Homeowner, Application, Valuation, Appraiser, AppraisalAppointment, Offer, Agreement, Lien, Inspector, Inspection, Settlement, Dispute)
- Endpoints: 53 (flat topology under /hei; every FK has a filtered-list reverse-reachability GET)
- Errors: 35
- Roles: 6 (Homeowner/Appraiser/Inspector entity-backed; InvestmentAnalyst/ClosingAgent/ComplianceOfficer opaque; SoD on dispute resolution)
- State machines: 10 (incl. parallel Agreement.covenant_status dimension; cyclic Offer counter/represent and Agreement dispute/re-proposal loops)
- Calculations: 8 (dual-variant appreciation_share SALE-capped vs BUYOUT-uncapped; provisional-vs-final offer max; round-then-sum settlement fee; combined-LTV threshold; waterfall + fund-capital conservation invariants)
- Concurrency rules: 1 (OCC on Agreement.version at settlement propose, CREATE-with-supersede)

Design instance counts: §1.8 = 18 instances (2 per each of 9 difficulty rules); §1.9 = 37 nodes (35 test recipes + 2 excluded_because stubs) across 9 sections; every one of 35 error codes triggered.

All three parse under yaml.safe_load. scaffold_lint.py: clean (446 calls, 0 violations). No bare `?` / nested `[` flow items.

Undeclared-constant patch: APPRAISER_BUFFER_MINUTES had no value declaration (used in validation priority-10 + ERR_APPRAISER_DOUBLE_BOOKED). Design §1.8 instance appraiser_buffer_overlap pins APPRAISER_BUFFER_MINUTES=60. Patched both the validation check line and the error condition line in SCAFFOLD.yaml to embed "(=60 minutes)" so PRD-gen picks up the concrete value. All other constants (MAX_COMBINED_LTV=0.75, INVESTMENT_LTV_CAP=0.30, ORIGINATION_FEE_PCT=0.03, SERVICING_FEE_PCT=0.01, ADMIN_FLAT_CENTS=50000, LOW_MAX=0.50, MODERATE_MAX=0.65, MONTHS_PER_YEAR=12) declared inline in calculation constants: blocks.

## Step 3: Copy INSTRUCTION.md — 2026-07-21T11:30:00.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md.

## Step 4: PRD generation — 2026-07-21T11:38:00.000Z

Output: workspace/PRD.md — 287 lines. Sections §1 Introduction, §2 Global Specs (2.1 RBAC, 2.2 response envelope verbatim, 2.3 pagination/filters, 2.4 common props + path validation, 2.5 monetary precision, 2.6 fund capital reconciliation, 2.7 OCC on settlement, 2.8 validation ordering + SoD, 2.9 logical clock), §3 Business Logic (3.1 intake, 3.2 valuation, 3.3 underwriting, 3.4 offer negotiation, 3.5 funding/lien/activation, 3.6 servicing/covenant, 3.7 exit/settlement, 3.8 disputes/SoD), §4 Endpoint Definitions (53 endpoints incl. POST /_clock/set_current_utc), §5 Error Catalogue (35 errors).

Hard contracts all PASS (field-name coverage, rule coverage incl. both calc dual-variants, §3 path purity). Verified: PRD endpoint set == scaffold endpoint set (53 == 53; 52 under /hei + 1 clock). Buffer constant landed as "within sixty minutes" for ERR_APPRAISER_DOUBLE_BOOKED.

Scaffold ambiguities resolved by doc-gen: clock input field to_iso8601 (framed as admin capability); all 13 entities common_fields:true; dispute-resolve replacement ending value from resolved_value_cents kept at scaffold abstraction; SoD asymmetry (finalize exempt, only dispute resolution/rejection gated) stated explicitly in §2.8/§3.7.

## Step 5: Unit test generation — 2026-07-21T12:04:00.000Z

test_helpers/ (9 files + __init__): types, api_client (one method per §4 endpoint), api_errors (35 IDs), assertions, factories, constants, test_users (entity-backed Homeowner/Appraiser/Inspector + opaque roles incl. make_compliance_headers for SoD co-1/co-2), fixtures (HEI lifecycle composites under_review→approved→presented_offer→funded→active→exit_initiated→proposed_sale_settlement + dual-basis/scheduling helpers).

test_suite/ (conftest + 8 files): test_01_intake_and_underwriting, test_02_offer_negotiation, test_03_scheduling, test_04_funding_lien_activation, test_05_servicing_covenant, test_06_settlement_calculations, test_07_settlement_finalize_dispute, test_08_not_found_lookups.

Counts: 71 tests total. Queue A (Difficulty) = 36 (all 18 instances × 2). Queue B (Corner) = 35 (all 35 non-stub instances × 1). Every docstring carries verbatim PRD citation + exactly one Design: line; programmatic check confirms no orphan tags / no shortfall; each citation ≥8-word grep-verified against PRD.md.

Skipped: 2 excluded_because corner stubs (appreciation_share_correctness_excluded, settlement_fee_rounding_excluded) — assertions owned by difficulty instances dual_variant_calc/appreciation_share_sale_vs_buyout + combinatorial_formula/settlement_fee_round_then_sum (cross-refs resolve). No PRD-filter drops.

## Step 6: Implementation generation — 2026-07-21T12:04:00.000Z

Files: start.sh (foreground, reads $PORT default 10000, binds 0.0.0.0, guarded pip install, exec python3 app.py), requirements.txt (flask==3.0.3), core.py (in-memory store starts empty, logical clock default 2026-07-01T00:00:00Z, envelope/money/date helpers, fund-capital reconciliation, 13 serializers), app.py (53 routes, auth/RBAC, validation ordering, state machines, calc engine).

PARTIAL-WRITE GUARD PASS: 53 @app.route == 53 Flask url_map rules == 53 scaffold endpoints. Both py files ast.parse OK. app.py imports and builds url_map cleanly.

Key behaviors: response envelope (meta/response_type/data, req_ id), validation priority chain 401→403authz→404path→403ownership→400body→404body-FK→409state→412OCC→403SoD→409cross→409/400temporal/constraint→422fiscal; combined_ltv exact Fraction ≤0.75 + risk bands; adjusted_start_value round-half-up; offer LTV cap floor 30%; appreciation SALE min(raw,cap) each-side-rounded / BUYOUT uncapped; settlement fee round-per-component-then-sum; conserved waterfall; cascades (offer-accept, settlement-finalize depth-3, covenant breach/cure); OCC expected_agreement_version→412; SoD dispute resolve/reject→403; appraiser 60-min buffer (exactly-60 allowed); inspector same-day; same-method valuation supersession; version bumps only where spec declares.

Impl-gen design decision flagged: appraisal-appointment "valuation must be PENDING APPRAISAL" gate — PRD names no explicit error → used ERR_INVALID_STATE (409) under priority-9 cross-entity. (Watch in Step 7.)

## Step 7: Test/iterate loop — 2026-07-21T12:07:00.000Z

CLEAN FIRST-SWEEP PASS. Iterations: 1 (single 8-round sweep as 2 waves of 4). 71/71 tests passing in ALL 8 rounds (verified against results.1.json..results.8.json). Tests deleted: none. test_helpers/ fixes: none. implementation/ fixes: none. No flakiness across 8 rounds. Known impl-gen judgement call (appraisal-appointment PENDING APPRAISAL gate → ERR_INVALID_STATE/409) did not trip any test.

## Step 8: PRD finalize — 2026-07-21T12:08:00.000Z

SKIPPED per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, 0 implementation/ fixes. PRD.md already determined every behavior the implementation exhibits at the Step-7 sites. PRD_FINALIZED.md not produced; Step 9 sources from PRD.md.

## Step 9: PRD complete — 2026-07-21T12:12:00.000Z

Output: workspace/PRD_COMPLETED.md. Source PRD.md 287 lines/43798 chars → PRD_COMPLETED.md 287 lines/44203 chars (+405 chars). 2 paragraphs revised in place, no new sections. Counts: 3 ambiguity-pins, 0 mismatch-revisions.

Changes:
- §3.2 — insert — ambiguity — appraisal-appointment "valuation must be PENDING appraisal" gate pinned to ERR_INVALID_STATE (409); PRD named no error (the flagged judgement call). (app.py:546-549)
- §3.2 — insert — ambiguity — appraiser double-booking boundary: "within sixty minutes" = windows separated by strictly <60 min; windows exactly ≥60 min apart do not conflict. (app.py:555-569)
- §3.8 — insert — ambiguity — resolve-created replacement settlement inherits voided settlement_type + mortgage_payoff_cents, records resolving officer as proposed_by_user_id; rejection does NOT increment agreement.version (resolve does +1). (app.py:1385-1390, 1203-1220, 1417-1418)

Verified already-pinned: fund capital reconciliation, LTV/risk-band boundaries, round-per-component fee + round-each-side-of-cap share, elapsed whole-calendar-months, OCC on propose, §2.8 validation ordering, covenant cycle, funding/finalize cascades. Numeric prose ranges (confidence_score/option_percentage/risk_adjustment_pct) not impl-validated; left unchanged (describe domain, not a reject).

## PIPELINE COMPLETE — 2026-07-21T12:12:00.000Z

All 9 steps done. workspace/PRD_COMPLETED.md exists. Final 8-round sweep all-green (71/71 × 8). Clean first-sweep pass, 0 fixes, Step 8 skipped, Step 9 = 3 ambiguity-pins.
