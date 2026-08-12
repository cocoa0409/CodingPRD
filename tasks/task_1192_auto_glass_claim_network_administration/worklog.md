# Worklog — task_1192_auto_glass_claim_network_administration

## Step 1: Create task directory — 2026-08-11T16:30:41.725Z

Task directory pre-assigned by launcher (no auto-index scan run): `tasks/task_1192_auto_glass_claim_network_administration/` with `workspace/` subdirectory. Both verified to exist. Step 1 treated as done per launcher instruction.

## Step 2: Generate scaffold — 2026-08-11T17:58:53.377Z

NOTE: The first scaffold subagent was terminated early by an API connection error after writing SCAFFOLD.yaml (1055 lines, valid, §1.0–§1.7 complete, no forbidden keys). A bounded follow-up subagent wrote only the two missing design files against the existing SCAFFOLD.yaml. Combined summary of the completed step:

SCAFFOLD.yaml (from first subagent): 13 entities, state machines for Claim/WorkOrder/Invoice/WarrantyClaim/FraudAlert/CalibrationEvent, 54 endpoints, full §1.0–§1.7 (scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles).

**Task 1192 — SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml written (harder-than-expert calibration)**

Files written:
- `/home/ubuntu/github/CodingPRD/tasks/task_1192_auto_glass_claim_network_administration/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1192_auto_glass_claim_network_administration/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

Difficulty instance count per rule (3 per rule, 27 total — above the ≥2/rule expert minimum):
- dual_variant_calc: 3 (Claim provisional-vs-final with OEM upcharge; GlassShop rolling-EMA 94.0 vs period-close 90.0; zero-deductible-state provisional-vs-final)
- combinatorial_formula: 3 (mode a: tier×origin×line-type pricing, submitted 212825; mode b: pinned tax-rounding order 3733 vs 3734; mode c: customer-responsibility cap evaluation-order)
- non_linear_state_machine: 3 (Claim supplement re-verify cycle; Invoice dispute/resubmit cycle; WorkOrder no-show/reschedule cycle)
- transitive_cascade: 3 (warranty-decide → strike → suspension depth-3; invoice pay → claim SETTLED depth-2; fraud CONFIRMED → claim DENIED + policyholder SUSPENDED depth-2)
- priority_pair_validation_conflict: 3 (state P5 vs business_safety P6; business_constraint P7 vs business_temporal P8; auth P2 vs existence P4)
- boundary_precision_check: 3 (fraud score ==100 inclusive FRAUD_HOLD gate; bay minutes 480/480 exact fit vs 481 overflow; warranty 365-day inclusive deadline ±1s)
- cross_entity_state_dependency: 3 (Claim→Policy, WorkOrder→CalibrationEvent, Claim→ChoiceDisclosureRecord)
- resource_temporal_overlap: 3 (MOBILE 45-min buffered half-open vs unit count; calibration rig strict half-open adjacency; IN_SHOP aggregate daily-minutes sum)
- compensating_invariant: 3 (invoice money conservation through DISPUTE→resubmit→APPROVE; bay-minutes schedule/cancel zero drift; fraud-score signal/dismissal exact reversal)

Corner instance count per section (86 total: 77 full test_recipes + 9 excluded_because stubs):
- entities: 23 (creation, defaults, computed/system fields, immutability, type constraints, 9 not-found cases, FK integrity)
- state_machines: 14 (initial state, invalid-from rejections, terminal lockdowns on Claim/WorkOrder/Invoice/WarrantyClaim/FraudAlert/CalibrationEvent, side-effect cascades)
- calculations: 7 (state deductible cap, zero-deductible WINDSHIELD-only condition, OEM endorsement waiver, 45-minute rapid-completion boundary, selector tier ranking + tie-break, ZIP-prefix eligibility, 730-day IN_SHOP warranty window)
- validations: 16 (missing auth header, inverted interval, both ownership mismatches, segregation-of-duties, ADAS routing, active-work-order block, reroute supersedes OFFERED, suspended policyholder, discontinued part, MOBILE_FEE on IN_SHOP, early completion, second open warranty, line price above agreement boundary 95001 vs 95000, audit incomplete/over-approve, missing state regulation)
- endpoints: 6 (capacity computed read, reverse-reachability lists, pagination envelope defaults, filtered fraud-alert list, shop PATCH, policies filtered list)
- errors: 9 excluded_because stubs (already covered by named §1.8 instances; all references verified to exist)
- rbac: 6 (4 cross-role denials + WAIVED RBAC split: shop denied, auditor allowed)
- cross_cutting_layers: 4 (both OCC stale-version rules with `${var}`-disciplined payloads, version increment chain, logical-clock default 2026-05-01T00:00:00Z)
- consistency_model: 1 (immediate visibility in same response)

Lint status: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (54 endpoints, 13 entities, 27 §1.8 + 77 §1.9 instances, 1071 calls scanned). All three files also parse clean under `python3 yaml.safe_load`. Cross-file checks: instance names unique across the union, all `grounds` refs resolve to §1.1–§1.6 elements, all OCC `expected_*_version` payloads reference captured `${var}`s. SCAFFOLD.yaml was not modified.

Known scaffold limitation (not modified per constraint): `ERR_POLICY_INACTIVE` is unreachable via the §1.5 surface (no endpoint transitions Policy to CANCELLED), so no corner instance triggers it.

## Step 3: Copy shared files — 2026-08-11T17:59:27.134Z

Copied `./INSTRUCTION.md` → `tasks/task_1192_auto_glass_claim_network_administration/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-11T18:16:44.271Z

## PRD Generation Summary — task_1192_auto_glass_claim_network_administration

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1192_auto_glass_claim_network_administration/workspace/PRD.md` — 7,124 words / 331 lines (332 with trailing newline). The withheld difficulty/corner index files were not opened.

**Section list**
- §1 Introduction (2 paragraphs: regulatory/business context + lifecycle scope and segregation of duties)
- §2 Global Specifications: 2.1 RBAC (headers, 6 roles, per-role `X-User-ID` identity translations incl. entity-backed Policyholder/GlassShop and 4 opaque roles), 2.2 API Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md`), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields), 2.4 The Logical Clock (startup default 2026-05-01T00:00:00Z, `to_iso8601`/`current_utc`), 2.5 Common Resource Properties (UUID `id`, `created_at`/`updated_at`, `version`; ChoiceDisclosureRecord carries only `id`+`created_at`), 2.6 Monetary Precision (integer cents, half-up, pinned per-line-then-sum, scores at 2 dp), 2.7 OCC (both rules), 2.8 Nested Retrieval + 9-level Validation Priority cascade, 2.9 Hierarchical Consistency (cascades + capacity/money conservation invariants)
- §3 Business Logic (7 subsections): 3.1 Network Configuration & Reference Data, 3.2 Claim Intake & Coverage Determination (provisional vs final deductible basis, supplement revision loop), 3.3 Customer Choice & Shop Routing (selector policy, tier-multiplier ranking, supersede), 3.4 Scheduling, Capacity & Fulfillment (bay minutes, 45-min mobile buffer, no-show cycle, calibration rig), 3.5 Invoicing, Agreement Pricing & Audit Settlement (tier multipliers 0.75/0.85/0.95, OEM 1.00, flat 5000/1500 fees, tax on summed parts subtotal, SOD, APPROVE/DISPUTE/REJECT branches, settlement fields), 3.6 Fraud Scoring & Investigation (40/35/25-point signals, inclusive 100 threshold, resolution cascades), 3.7 Warranty Rework & Network Quality (365/730-day inclusive windows, strikes→suspension contagion, rolling EMA vs period-close mean with the 97.0/95.0 worked example)
- §4 Endpoint Definitions: 54-row table (4 columns: Method, Path, Description, Authorized Role(s)); 201-create/200-modify rule stated above
- §5 Error Code Catalogue: 55-row table (2 columns: Error ID, HTTP Status Code); document ends at §5 with no audit footer

**Coverage audit results**
- Contract 1 (Field-Name Coverage): 120/120 required identifiers backticked (86 entity fields + endpoint-only inputs/query/path params + envelope/header fields). First pass missed `invoice_id` and `original_work_order_id`; both repaired in §3.5/§3.7 narrative, re-run to 0 missing. PASS
- Contract 2 (Rule Coverage): 9/9 validation priority categories expressed as an explicit ordered cascade ("earlier category masks later"); 2/2 OCC rules fully expressed (`expected_claim_version`→`ERR_STALE_CLAIM_VERSION` 412; `expected_work_order_version`→`ERR_STALE_WORK_ORDER_VERSION` 412, stale-version framing only); 40/40 state-machine transitions with preconditions→error IDs and all side-effect cascades (supersede, bubble-up, rework, fraud, settlement); 9/9 calculations in reconstruction-test prose (no operator syntax, no fuzzy wording — grep-verified); 55/55 error IDs present in §2/§3 prose AND §5 table; 66/66 enum/state/role tokens present; sibling branches (APPROVE/DISPUTE/REJECT, VERIFIED/FAILED/WAIVED, CONFIRMED/DISMISSED, APPROVE_REWORK/DENY, MOBILE/IN_SHOP) at equal density. PASS
- Contract 3 (§3 Path Purity): 494 backticked tokens scanned in §3 — 0 path tokens, 0 bare HTTP methods, 0 method+path combos. PASS

**Zero-Silence Rule adjudications** (scaffold readings requiring judgment, resolved strictly within SCAFFOLD.yaml content)
1. `ERR_ADAS_CERTIFICATION_REQUIRED` scope: the validation row mentions routing/scheduling, but the routing transition enforces ADAS via the selector eligibility filter (`ERR_SHOP_NOT_ELIGIBLE`/`ERR_NO_ELIGIBLE_SHOP`); the PRD names the ADAS error at scheduling and routes ADAS enforcement through eligibility — faithful to both scaffold loci.
2. Calibration-verify ownership: scaffold lists the shop-ownership precondition only on the VERIFIED branch; PRD states VERIFIED/FAILED are recorded by the owning shop operator while WAIVED is `NetworkAuditor`-only (per roles + transition preconditions), without inventing an ownership check on the auditor path.
3. ChoiceDisclosureRecord (`common_fields: false`): stated explicitly as append-only/immutable, carrying only `id` and `created_at`, `updated_at`/`version` absent.
4. Ownership applies_to enumeration (validation priority 3) expressed as a complete endpoint-family list in §2.8 so cancel/supplement/choice-disclosures/warranty-claims (Policyholder) and accept/decline/schedule/mark-no-show/complete/calibration-events/invoices/submit (ShopOperator) are all covered.

## Step 5: Generate unit tests — 2026-08-11T18:50:57.560Z

## Task 1192 — Unit test generation complete

**test_helpers/ written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1192_auto_glass_claim_network_administration/test_helpers/`):
- `types.py` — 13 entity TypedDicts (ChoiceDisclosureRecord correctly carries only `id`+`created_at`, no `updated_at`/`version`) + 17 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with 45 endpoint methods covering every PRD §4 endpoint incl. `set_clock`
- `api_errors.py` — all 55 `ApiErrorId`s + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions + `assert_invoice_conservation` / `assert_capacity_conservation` invariant checkers
- `factories.py` — per-entity payload factories, line builders, audit/routing payload builders
- `constants.py` — tier multipliers, fraud point values (40/35/25, threshold 100), OEM upcharge 1/4, MOBILE_FEE 5000, MATERIALS 1500, EMA alpha 0.3, warranty windows 365/730, 45-min mobile buffer
- `test_users.py` — shared opaque-role headers + mandatory per-instance builders `make_policyholder_headers` / `make_shop_operator_headers` for the two entity-backed roles
- `fixtures.py` — composite builders: `setup_network`, `setup_claim_verified`, `setup_work_order_offered/accepted/scheduled/completed`, `setup_invoice_submitted/approved/paid`, `setup_warranty_filed`, `setup_calibration_event`, plus step helpers; identity threading via the builders throughout
- `__init__.py` — barrel export

**test_suite/ written**: `conftest.py` + 10 test files (`test_01_reference_data_and_reads` … `test_10_listings`).

**Test counts**: 131 tests total, all tagged.
- Queue A (Difficulty): 27/27 instances, exactly 2 tests each = **54 tests**
- Queue B (Corner): 77/77 non-stub instances, 1 test each = **77 tests**
- 9 `excluded_because` stubs in the errors section were NOT translated; all 9 `difficulty_instance` pointers verified to resolve to real queue-A instances.

**Skipped instances**: none. Every difficulty and non-stub corner instance passed the PRD-first two-condition filter (the PRD covers every asserted rule with verbatim prose; §2.8's ordered validation cascade covers the three priority-conflict instances).

**Verification status**:
- `py_compile` clean on all files
- `pyflakes` clean on all modules (only intentional barrel re-export warnings in `__init__.py`, which are suppressed by design; all other files zero warnings)
- `pytest --collect-only`: **131 tests collected**, no errors
- Automated audit: every test docstring ends with exactly one `Design:` tag resolving to a real instance; every difficulty instance has ≥2 tags, every non-stub corner instance ≥1; no orphan/dual tags
- Verbatim-citation audit: all 131 docstrings contain a ≥8-word span that greps literally in `workspace/PRD.md`
- No `skip`/`skipif`/`xfail` markers; no scaffold references in generated code

One judgment call worth noting: exact-equality assertions on logical-clock timestamps (`paid_at`, `created_at`) were written as `startswith(...)` prefix checks, because PRD §2.5's three-fractional-digit serialization makes `…T12:00:00.000Z` vs `…T12:00:00Z` an underdetermined rendering detail — the asserted rule ("stamps from the logical clock") is tested at full strength.

## Step 6: Generate implementation — 2026-08-11T18:50:57.560Z

## Summary

**Task:** task_1192_auto_glass_claim_network_administration — full Python + Flask implementation generated.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1192_auto_glass_claim_network_administration/workspace/implementation/`):
- `start.sh` — executable launcher; guarded dependency install (`import flask` check, pip install only when missing), `exec python3 app.py` in foreground, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0,<4`
- `app.py` — Flask entry, error handlers (ApiError, 400/404/405/500 envelopes), global RLock per request
- `db.py` — in-memory dict store (13 entity maps), logical clock starting exactly `2026-05-01T00:00:00Z`, ms-precision ISO-8601 UTC stamps, UUID ids, insertion-seq ordering
- `errors.py` — ApiError + all 54 error-id constants
- `response.py` — envelope helpers (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`; list meta adds `limit/offset/total_count/has_more`)
- `middleware.py` — X-User-ID/X-User-Role auth, role sets, payload sanity validators, pagination (default 10, min 1, max 100, offset 0)
- `serialize.py` — per-entity views (shop read computes period_close score)
- `services/pricing.py` — tier multipliers (0.75/0.85/0.95), OEM 1.00 rule, MOBILE_FEE 5000 flat, MATERIALS 1500×tier, HALF_UP per-line rounding, pinned per-line→parts-subtotal→tax→total order, deductible determination (state cap, zero-deductible rule), OEM upcharge 25%
- `services/fraud.py` — REPEAT_WINDOW (+40/90d), SOLICITATION (+35), RAPID_COMPLETION (+25/<45min/WINDSHIELD), SCORE_THRESHOLD gate at 100 (inclusive), DISMISSED reversal (floor 0), CONFIRMED hold→DENIED + policyholder SUSPENDED
- `services/scoring.py` — rolling EMA α=0.3 (HALF_UP 2dp per update) and read-time period-close mean
- `services/capacity.py` — bay-minute budget, mobile [start, end+45min) buffered overlap, calibration rig strict half-open overlap
- `services/claims.py` — WORK_AUTHORIZED→COVERAGE_VERIFIED bubble-up with assigned_shop_id clearing
- `routes/` — `reference.py` (policyholders, state-regulations, policies, glass-shops incl. PATCH + capacity + work-orders, part-catalog-entries incl. PATCH + line-items), `claims.py` (intake w/ FRAUD_HOLD, verify-coverage, deny, cancel w/ cascade, supplement loop, choice-disclosures, routing-decisions w/ OCC + selector ranking + supersede), `workorders.py` (accept/decline/schedule w/ OCC + capacity/mark-no-show/complete w/ ADAS + rapid-completion + rework cascade/cancel, calibration events + verify w/ WAIVED auditor-only), `invoices.py` (create/submit/resubmit, audit-decisions APPROVE/DISPUTE/REJECT w/ SOD + full-coverage checks, pay), `fraud.py`, `warranty.py` (365d/730d inclusive window, ALREADY_OPEN, rework spawn + 3-strike suspension), `clock.py`

**Endpoints registered:** 54 — exact match to the PRD §4 endpoint table.

**Storage:** in-memory only, store starts empty on every boot; no seeding/preloading anywhere (verified by grep and by empty-list reads after fresh boot).

**Validation/boot status:** `py_compile` clean on all 14 Python files; `bash start.sh` boots on default port 10000 and on a custom `PORT`, responding within seconds. Four live smoke suites passed against the running server: full lifecycle (intake→verify→disclose→route→accept→schedule→capacity→complete→invoice→submit→SOD-403→approve→pay→SETTLED with exact tax/total/customer-responsibility math), fraud suite (repeat-window, solicitation crossing gate, FRAUD_HOLD intake, DISMISSED release, CONFIRMED deny+suspend, suspension blocking intake, reversal), flow suite (state-cap deductible, supplement loop resetting deductible, selector tier ranking, stale-OCC 412 on both claim and work order, bay-capacity 409, mobile-capability 422, no-show recovery, dispute→resubmit cycle, ERR_INVOICE_EMPTY, price-exceeds 402), and hard-paths suite (ADAS complete gate, calibration slot half-open overlap incl. touching-endpoint allowed, WAIVED permission 403, mobile buffer violation + boundary-OK, rapid-completion signal, warranty window inclusive boundary, rework cascade to REWORK_COMPLETED, warranty-strike accounting, claim-cancel cascade, audit-score divergence rolling=97.0 vs period_close=95.0).

Orchestrator verification: route cross-check confirms implementation registers exactly the 54 (method, path) pairs SCAFFOLD.yaml declares — 0 missing, 0 extra. `pytest --collect-only` on test_suite yields 131 tests, no errors.

## Step 7: Run tests and iterate — 2026-08-11T19:09:57.408Z

Clean 8-round parallel sweep: all 8 rounds 131/131. Summary for worklog:

- **Iterations run:** 2 sweeps (8 parallel rounds each). Sweep 1: 110–111/131 per round, 21 unique failing tests (20 deterministic, 1 parallelism-induced restart flake). Sweep 2: 131/131 in all 8 rounds.
- **Tests deleted:** none.
- **Fixes applied to `test_helpers/`:** none.
- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1192_auto_glass_claim_network_administration/test_suite/test_09_warranty.py` (`_complete_work_order_on_shop`, used by `test_third_strike_suspends_shop` / `test_suspended_shop_blocks_acceptance`): zero-pad hour in f-string timestamps (`T{hour:02d}:...`) — hour=9 produced `2026-05-01T9:00:00Z`, not valid ISO 8601, so the PRD-required datetime validation correctly rejected the fixture's schedule request.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1192_auto_glass_claim_network_administration/test_suite/test_08_fraud.py` (`test_intake_at_exactly_100_diverts_to_fraud_hold`): relaxed `assert len(alerts) == 1` to filter for exactly one `SCORE_THRESHOLD` alert with `score_contribution == 0`. PRD §3.2/§3.6 verbatim-cover the FRAUD_HOLD diversion and the zero-point threshold alert, but the no-other-alerts exclusivity is not uniquely derivable: PRD §3.6 defines REPEAT_WINDOW as firing unconditionally "at claim intake when another claim of the same policyholder exists … inside the trailing ninety-day window", so a PRD-faithful implementation may also open a REPEAT_WINDOW alert for the held claim (partial-coverage split per STEP 1c; FRAUD_HOLD + threshold-alert assertions kept).
- **Fixes applied to `implementation/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1192_auto_glass_claim_network_administration/workspace/implementation/routes/invoices.py` (`_line_ref` + audit_decision): accept positional integer `line_index` (into the invoice's `sorted_created` line order, same as the list endpoint) as an adjustment-line reference alongside the existing id-key aliases. PRD §3.5 requires "the `adjustment_lines` must cover every line item exactly once" but is silent on the reference mechanism; the coverage/over-line `ERR_AUDIT_INCOMPLETE` checks are unchanged. Fixed the 15-test ERR_AUDIT_INCOMPLETE cluster (approve/dispute/pay/conservation/score/settlement tests).
  - `/home/ubuntu/github/CodingPRD/tasks/task_1192_auto_glass_claim_network_administration/workspace/implementation/routes/claims.py` (`create_routing_decision`): admit claims in `WORK_AUTHORIZED` in addition to `COVERAGE_VERIFIED`. PRD §3.3's verbatim routing effects — "Every existing linked work order in `OFFERED` or `NO_SHOW` is moved to `SUPERSEDED`" — are only reachable when a prior routing left the claim in `WORK_AUTHORIZED` with an OFFERED/NO_SHOW work order; the `ERR_ACTIVE_WORK_ORDER_EXISTS` (ACCEPTED/SCHEDULED) gate and all other gates are unchanged. Fixed `test_rerouting_supersedes_offered_work_order` and `test_active_work_order_blocks_rerouting`.
- **Flake note:** `test_immediate_visibility_in_same_response` failed all 8 rounds of sweep 1 with "server could not be restarted" but passed standalone and in all 8 rounds of sweep 2 — infrastructure timing under 8-way parallel load, no code issue.

## Step 8: Finalize PRD — 2026-08-11T19:15:58.425Z

`PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1192_auto_glass_claim_network_administration/workspace/PRD_FINALIZED.md` with exactly three inline revisions, each traced to a Step 7 item. The fraud-threshold test relaxation and the warranty timestamp fixture fix required no PRD edits: the former is already verbatim-covered by §3.2/§3.6 (implementation `routes/claims.py:137` calls `evaluate_repeat_window` unconditionally after the FRAUD_HOLD gate, exactly as §3.6's unconditional REPEAT_WINDOW wording prescribes), and the latter was a pure test-fixture bug (non-zero-padded hour in an ISO string).

**Summary for worklog:**

- PRD.md vs PRD_FINALIZED.md line counts: 331 → 331 (0.0% delta; all edits are same-line revisions/inline insertions, no sections added).

Changes:
- §3.3 — revise — routing admission widened from "a `COVERAGE_VERIFIED` claim (else `ERR_CLAIM_NOT_COVERAGE_VERIFIED`)" to "a claim in `COVERAGE_VERIFIED` or `WORK_AUTHORIZED` — the latter is the re-routing path… — any other state rejected with `ERR_CLAIM_NOT_COVERAGE_VERIFIED`" — `workspace/implementation/routes/claims.py:323-328`.
- §3.3 — revise — routing effect on the claim changed from "moves `COVERAGE_VERIFIED` → `WORK_AUTHORIZED`" to "is left in `WORK_AUTHORIZED` — moving `COVERAGE_VERIFIED` → `WORK_AUTHORIZED` on the first routing and remaining `WORK_AUTHORIZED` on a re-routing" — `workspace/implementation/routes/claims.py:386-387`.
- §3.5 — insert — pinned the `adjustment_lines` line-reference mechanism: id-key aliases (`line_item_id`, `invoice_line_item_id`, `line_id`, `id`) or zero-based integer `line_index` into the invoice's creation-ascending line order (same as the line-items list endpoint), id-key precedence when both present, unresolvable/duplicate references rejected as `ERR_AUDIT_INCOMPLETE` — `workspace/implementation/routes/invoices.py:213-221, 257-288`.

Per-edit pre-edit search log:
1. §3.3 routing admission (edit 1): (a) subject — claim states from which POST `/claims/{id}/routing-decisions` is admitted. (b) enumerated/read: `routes/claims.py:310-388` (sole routing endpoint, all gates), `routes/claims.py:214-258` (cancel/supplement state gates — unchanged by edit), `services/claims.py:17-27` (`bubble_up_claim` WORK_AUTHORIZED→COVERAGE_VERIFIED revert — consistent, not exclusive), `routes/workorders.py:218-220` (completion cascade), `routes/warranty.py:140-157` (rework WO creation bypasses routing, leaves claim status untouched), `errors.py:33`, plus PRD cross-references §2.7 ("an earlier routing decision mutated the claim in between") and §3.4 ("freeing the adjuster to route again" — non-exclusive, still true). (c) wording scoped explicitly to routing ("the latter is the re-routing path") so supplement's strict COVERAGE_VERIFIED gate is not implied to widen.
2. §3.3 routing effects (edit 2): (a) subject — claim status/fields after a successful routing decision. (b) enumerated/read: `routes/claims.py:366-388` (unconditional `claim["status"] = "WORK_AUTHORIZED"`, `assigned_shop_id` set, `touch` version increment; OFFERED/NO_SHOW→SUPERSEDED loop), `test_suite/test_03_routing_and_choice.py:126-147` (asserts claim remains `WORK_AUTHORIZED` with updated `assigned_shop_id` after re-routing), `services/claims.py` bubble-up (unaffected — only fires on decline/cancel, never during routing since the new OFFERED WO keeps the claim non-terminal). (c) chose "is left in `WORK_AUTHORIZED` — moving … on the first routing and remaining … on a re-routing" instead of a narrower "stays" phrasing, to cover both admission states without contradicting the first-routing transition wording elsewhere.
3. §3.5 adjustment line reference (edit 3): (a) subject — how an `adjustment_lines` entry identifies the invoice line it adjusts. (b) enumerated/read: `routes/invoices.py:213-221` (`_line_ref`, the only resolver), `routes/invoices.py:243-288` (`audit_decision` coverage/duplicate/over-line checks — unchanged semantics), `routes/invoices.py:59-60` + `db.py:107-109` (`_invoice_lines`/`sorted_created` creation-ascending order with `_seq` tiebreak), `routes/invoices.py:149-156` (GET `/invoices/{id}/line-items` uses the same ordering), grep for `line_index|line_item_id|invoice_line_item_id|line_id|adjustment_lines|_line_ref` across `implementation/` (no other consumers), `test_helpers/factories.py:167-169`, `test_helpers/fixtures.py:327`, `test_suite/test_07_audit_and_settlement.py` (all use `line_index`). (c) added "when an entry carries both an id-key reference and a `line_index`, the id-key reference takes precedence" to match the resolver's key-first fallthrough, and folded unresolvable/duplicate references into the existing `ERR_AUDIT_INCOMPLETE` coverage language rather than inventing a new error pathway.

## Step 9: Complete PRD — 2026-08-11T19:25:53.325Z

## Summary

**Source file (PRD_FINALIZED.md) vs PRD_COMPLETED.md:**
- PRD_FINALIZED.md: 331 lines, 52,735 chars
- PRD_COMPLETED.md: 332 lines, 55,287 chars
- Char delta: +2,552 chars

**Counts:**
- Ambiguity-pins: 11
- Mismatch-revisions: 2

**Changes (one bullet each):**

- §2.1 — insert — ambiguity — Pin that an `X-User-ID` for Policyholder that does not resolve to a persisted Policyholder yields `ERR_POLICYHOLDER_NOT_FOUND` (404) on identity-backed endpoints — implementation/routes/claims.py:77-79
- §2.2 — insert — ambiguity — Pin `has_more` formula `(offset + page_size) < total_count` — implementation/response.py:27
- §2.3 — revise — ambiguity — Pin that `limit > 100` is silently clamped to 100 (not rejected), and that non-integer/`<1` limit or non-integer/negative offset → `ERR_INVALID_REQUEST` — implementation/middleware.py:145-167
- §2.4 — revise — mismatch — Change "advances the logical clock" to "sets the logical clock … forward or backward" (impl permits moving backward) — implementation/routes/clock.py:22
- §2.5 — revise — ambiguity — Pin `version` starts at 1 and `updated_at` initializes equal to `created_at` — implementation/db.py:62-71
- §2.8 — revise — mismatch — Renumber/reorder the validation cascade: path-existence precedes ownership, then body-resource references, then state/shape (impl resolves claim before checking ownership, and resolves `requested_shop_id`/parts before state checks) — implementation/routes/claims.py:57-70, 310-322; implementation/routes/invoices.py:104-108
- §3.1 — insert — ambiguity — Pin that PATCH /glass-shops always increments `version` even when no fields are modified — implementation/routes/reference.py:230-238
- §3.2 — insert — ambiguity — Pin that the FRAUD_HOLD threshold gate and the REPEAT_WINDOW evaluation are independent (REPEAT_WINDOW still fires when score already ≥100) — implementation/routes/claims.py:132-137
- §3.4 — insert — ambiguity — Pin that completion's claim cascade fires only when claim is currently `WORK_AUTHORIZED`, and the warranty-claim cascade fires only when the linked warranty claim is currently `APPROVED_REWORK` — implementation/routes/workorders.py:218-231
- §3.5 — insert — ambiguity — Pin that an empty `line_items: []` is allowed at invoice creation; `ERR_INVOICE_EMPTY` only fires at submit — implementation/routes/invoices.py:87-95, 194-203
- §3.5 — insert — ambiguity — Pin that resubmission from DISPUTED without `revised_line_items` retains existing lines, clears each line's `approved_amount_cents`/`approved_origin` to null, and resets totals — implementation/routes/invoices.py:192-200
- §3.5 — revise — ambiguity — Pin `approved_amount_cents` must be integer between 0 and `line_total_cents` inclusive; also pin that invalid `approved_origin` (non-OEM/AFTERMARKET) → `ERR_INVALID_REQUEST` (400) — implementation/routes/invoices.py:273-280
- §3.5 — insert — ambiguity — Pin that REJECT leaves the invoice's `approved_total_cents`, `adjustment_total_cents`, and per-line approval fields unchanged from pre-rejection values — implementation/routes/invoices.py:329-334
- §3.6 — insert — ambiguity — Pin that REPEAT_WINDOW fires at most once per intake (regardless of how many earlier claims match) and records the new claim's id as triggering `claim_id` — implementation/services/fraud.py:42-55
- §3.7 — insert — ambiguity — Pin that the rework work order's `service_mode`, `scheduled_start`, `scheduled_end`, `completed_at` all start null — implementation/routes/warranty.py:144-156
- §3.7 — revise — ambiguity — Pin that rolling EMA is updated in the order audit decisions are received (no re-sorting); removed the "ties broken by invoice created_at" clause since impl doesn't sort — implementation/services/scoring.py:25-34

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_1192_auto_glass_claim_network_administration/workspace/PRD_COMPLETED.md`
