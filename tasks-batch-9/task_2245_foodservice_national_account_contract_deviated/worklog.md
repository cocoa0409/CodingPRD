# Worklog — task_2245_foodservice_national_account_contract_deviated

## Step 1: Create Task Directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2245_foodservice_national_account_contract_deviated/` and `tasks/task_2245_foodservice_national_account_contract_deviated/workspace/` (pre-allocated directory name used verbatim; no index scan performed).

## Step 2: Generate Scaffold — 2026-09-01T12:47:00.000Z

Scaffold for task 2245 is complete and lint-clean.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2245_foodservice_national_account_contract_deviated/`):
- `SCAFFOLD.yaml` (163 KB) — §1.0–§1.7 only; top-level keys are `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (neither design key present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (142 KB) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (349 KB) — single key `scaffold_corner_design`

**Contents**
- **Entities: 15** — Operator, Manufacturer, DistributionCenter, Product, Contract, ContractTier, DcCoverage, SubstitutionRule, DeviationAgreement, BillBackClaim, OrderLine, PriceChangeNotice, PricingDispute, RebatePeriod, MarketIndexQuote (flat/hybrid topology, FK reverse-reachability verified)
- **Endpoints: 75** under prefix `/nac`, incl. reference-data CRUD, contract lifecycle actions, deviation approval chain, bill-back claim/write-off, order-line repricing, dispute resolve, rebate settle, compliance report, and `POST /nac/_clock/set_current_utc` (SystemAdmin only) returning `{current_utc, expired_contract_ids, expired_deviation_ids}`
- **Calculations: 13** — cost-plus tiered markup (tiered_pricing), deviated net price + bill-back recovery, out-of-market service fee, contracted-purchase-percentage compliance, rebate accrual/settlement waterfall, market-index repricing, dispute credit, incl. one dual-variant (prospective vs retroactive tier pricing)
- **State machines: 11 blocks** — Contract, DeviationAgreement, BillBackClaim, PriceChangeNotice, PricingDispute, RebatePeriod, ContractTier, DcCoverage, SubstitutionRule, plus OrderLine modelled twice as parallel dimensions (`pricing_status`, `billback_status`)
- **Validations: 42** (3-priority auth/authz/existence ladder then business rules); **Errors: 61**, every code verified triggerable (programmatic sweep: `uncovered []`); **Roles: 7**; **Concurrency rules: 2** (`expected_contract_version`, `expected_deviation_agreement_version`)
- **§1.8: 9 `rule_id` blocks / 19 instances**
- **§1.9: 9 sections / 71 instances** — Entities 12, State Machines 15, Calculations 17, Validations 12, Endpoints 5, Errors 1, RBAC 4, Cross-Cutting Complexity Layers 4, Consistency Model 1; 56 carry full `test_recipe`, 15 are `excluded_because` stubs

**Lint verdict (verbatim)**
```
Coverage
  §1.5 endpoints declared:    75
  §1.1 entities declared:     15
  §1.8 instances scanned:     19
  §1.9 instances scanned:     56
  Calls scanned (§1.8+§1.9):  1304

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Hard constraint respected: no sibling `task_*/` directory was listed, read, globbed, or grepped — the scaffold derives solely from the verbatim scenario text and the generator skill's own spec.

## Step 3: Copy Shared Files — 2026-09-01T12:50:35.183Z

Copied `./INSTRUCTION.md` → `tasks/task_2245_foodservice_national_account_contract_deviated/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-01T13:07:55.826Z

PRD generated and audited.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2245_foodservice_national_account_contract_deviated/workspace/PRD.md` — **447 lines**, ending at §5 with no audit footer.

**Structure**
- §1 Introduction — 3 paragraphs (domain framing: cost-plus national account contracts, deviated off-invoice pricing with manufacturer bill-back, derived-money and reversible-correction design principles).
- §2 Global Specifications — 11 subsections: 2.1 Identity/RBAC (7 roles, `opaque` vs `entity_backed` translated into explicit ownership prose), 2.2 API Response Structure (pasted byte-for-byte from `section-2.2-response-structure.md`, verified identical), 2.3 Pagination and Collection Filtering (defaults 10/1/100/0, `created_at` ascending, every filter param enumerated), 2.4 Resource Addressing and Common Properties (flat topology, all 15 path params + 15 `*_NOT_FOUND` codes, `id`/`created_at`/`updated_at`/`version` semantics), 2.5 Logical Clock and Interval Conventions (startup `2026-08-01T00:00:00Z`; closed vs half-open intervals per entity), 2.6 Money/Percentages/Rounding, 2.7 Optimistic Concurrency (both stale-version rules with write endpoint, occ field, error, 412), 2.8 The Order in Which a Request Is Rejected (all 42 priorities in order with full `applies_to` sets), 2.9 Cascades and Version Bookkeeping, 2.10 Ledger Conservation (both invariants), 2.11 Segregation of Duties and Posture Gating.
- §3 Business Logic — 9 subsections: reference data/catalogue; contract construction (tier bands, DC coverage buffer, substitution rules); contract lifecycle (sign/amend/suspend/terminate/expiry with the asymmetric cascades); deviated pricing negotiation; the order line (tier pricing, service fees, substitution, invoicing, repricing); cost change notices + market indexing + 4-hop cascade; compliance/rebate accrual/settlement/reversal; bill-back recovery + remittance waterfall + reversal; pricing disputes + retroactive audit repricing + 4-hop credit cascade.
- §4 — 4-column table, 75 endpoint rows, preceded by the 201-vs-200 paragraph. §5 — 2-column table, 61 error rows.

**Coverage audit (all three Hard Contracts PASS)**
1. **Field-name coverage — PASS.** 156/156 lowercase identifiers (all `entities[].fields[].name`, all endpoint `input` fields, query/path params, and the `compliance-report` + clock output field names) appear verbatim in backticks; 0 missing. Second pass: 0 missing enum values across all entity enums; 61/61 error IDs present; 75/75 endpoints present with **0 role-list mismatches** and 0 extras; all 61 HTTP statuses match the scaffold exactly.
2. **Rule coverage — PASS.** All 54 state-machine transitions covered (37 matched literally on the `FROM → TO` arrow; the remaining 17 verified by hand as covered in from-state-set or cascade prose, e.g. "permitted from `DRAFT`, `PENDING_SIGNATURE`, `ACTIVE` or `SUSPENDED`"). All 42 validations rendered in priority order with their error IDs and full endpoint sets (priority 6's 14 endpoints plus the DRAFT-or-ACTIVE trio exception; priority 12's 5 endpoints; both segregation pairs; posture trio; ceiling pair). All 13 calculations written out with pinned operation order, both `contract_line_price` variants (prospective vs retroactive tier), the fee-waiver order (`extended_price_cents`, never `invoice_total_cents`), per-line rebate rounding, and every constant value (500,000 cents; 60%; 95/90/80 → 4.00/3.00/1.50/0.00; 10.00% / 7 days; 0.50%; 80.00% / breach limit 1; 3 revision rounds; 14-day coverage buffer; 30-day notice window). All 40 endpoints with `side_effects` reflected. Both OCC rules framed strictly as stale-version — 0 occurrences of "simultaneous", "race condition", "concurrent" or "at the same time".
3. **§3 path purity — PASS.** 0 backticked tokens in §3 start with `/`, are a bare HTTP method, or combine method+path; 0 plain-text `/nac...` mentions in §3. Endpoints referenced only by state-transition framing, role + gerund action, or capability description.

Two deliberate precision calls worth flagging to the implementer: the scaffold's endpoint-level summary for the clock sweep loosely says contract expiry cascades "tiers and coverages", but the authoritative `ACTIVE → EXPIRED` transition supersedes **no** tiers — the PRD follows the transition and states that asymmetry against `AMENDING → EXPIRED` and termination explicitly. And `shortfall_pct` (no scaffold formula) is defined as `contracted_purchase_pct_target` minus `latest_compliance_pct`, rounded half up to two decimals, signed, with all latest-period fields null when the contract has no `CLOSED`/`SETTLED` period. The two withheld design files were never opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-09-01T14:58:31.882Z

All 18 test modules are complete. Final state:

## Files written

**`/home/ubuntu/github/CodingPRD/tasks/task_2245_foodservice_national_account_contract_deviated/test_helpers/`** (9 files, Stage 1): `__init__.py`, `types.py`, `constants.py`, `factories.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `fixtures.py`, `test_users.py`.

**`.../test_suite/`** (Stage 2): `conftest.py` plus 18 modules — 94 tests.

| module | tests | source |
|---|---|---|
| test_01…test_09 | 38 | queue A (Difficulty) |
| test_10_entity_contracts | 12 | Corner/Entities |
| test_11_state_machine_paths | 9 | Corner/State Machines |
| test_12_calculation_matrices | 13 | Corner/Calculations |
| test_13_validation_rules | 10 | Corner/Validations |
| test_14_endpoint_behaviors | 4 | Corner/Endpoints |
| test_15_error_catalogue | 1 | Corner/Errors |
| test_16_rbac | 4 | Corner/RBAC |
| test_17_concurrency_versions | 2 | Corner/Cross-Cutting Complexity Layers |
| test_18_consistency | 1 | Corner/Consistency Model |

## Instances translated vs skipped

- **Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`): 19 of 19** non-stub instances translated (38 tests — several instances carry both a prospective and a retroactive/variant leg).
- **Queue B (`SCAFFOLD_CORNER_DESIGN.yaml`): 55 of 56** non-stub instances translated (56 tests). The yaml's own 15 `excluded_because:` stubs were correctly not emitted.
- **Skipped (1, PRD-first filter):** `Corner/Endpoints/reprice_is_allowed_only_while_the_lines_period_is_open` — §3.5 states the "rebate period … must still be `OPEN`" precondition for reprice, but neither the §2.8 ladder nor the §5 catalogue assigns an error code to violating it, so the instance's asserted `ERR_ORDER_LINE_INVALID_STATE` is not uniquely derivable. No placeholder, no xfail: the gap stays a gap.

## Verification (all clean)

Re-ran the audit script (`/tmp/audit_2245.py`) over the whole suite: **94 tests / 74 distinct `Design:` tags / 0 problems** — every test has exactly one trailing `Design:` line, every tag resolves to a real `name:` in one of the two design yamls, and every `PRD §X: "quote"` citation was matched verbatim (whitespace-normalized) against the text under that PRD heading. No `skip`/`xfail` anywhere; no docstring mentions the scaffold or its section numbers. All modules byte-compile, import cleanly, and have zero unused imports; no test calls `bootstrap_partners()` more than once.

## Design defects worked around

- The corner yaml uses `DAIRY` as a `product_class_code`; the PRD enum is PROTEIN/PRODUCE/FROZEN/DRY_GROCERY/DISPOSABLES/BEVERAGE/SPECIALTY, so `BEVERAGE` was substituted wherever `DAIRY` appeared.
- The Endpoints clock-sweep instance would have left `EXPIRED` vs `TERMINATED` ambiguous for the deviation; its window now ends beyond the contract term (`2026-11-01`) so only the contract-expiry cascade can move it.
- The design's envelope wording ("success false, data null") does not match the framework's actual `response_type: error` / `data.error_id` envelope; `validate_error` covers the real shape and the error-catalogue test asserts `error_id` plus a non-empty `message`.

## Step 6: Generate Implementation — 2026-09-01T14:58:31.882Z

The implementation is complete and verified.

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_2245_foodservice_national_account_contract_deviated/workspace/implementation/` — 21 Python modules (3,482 lines) plus `start.sh` and `requirements.txt`:

- **Entry/infra:** `app.py` (blueprint registration + `ApiError`/`HTTPException`/`Exception` handlers), `start.sh` (guarded pip install, `exec python3 app.py`, honors `$PORT`, default 10000), `requirements.txt` (`Flask==3.0.3`)
- **Core:** `errors.py` (62 `ERR_*` ids + status map), `db.py` (in-memory `Store`, 15 collections, logical clock), `util.py` (Decimal/ROUND_HALF_UP money + interval helpers), `response.py` (meta envelope), `middleware.py` (header auth, 7 roles, entity-backed ownership, 15 resolvers), `validation.py` (typed field coercion, pagination)
- **Services:** `services/pricing.py` (tier selection, list/deviated price, service fees, substitution), `compliance.py` (measurement, rate tiers, accrual split, posture), `billback.py` (claim sweep, exposure, cash waterfall + reversal), `cascade.py` (termination, amendment supersession, clock expiry sweep, notice cascade, credit cascade)
- **Routes:** `routes/common.py` plus 8 blueprints — `reference` 11, `contracts` 20, `deviations` 6, `notices` 8, `rebates` 6, `order_lines` 6, `billback` 10, `disputes` 8

## Endpoint count

**75 routes registered under `/nac`**, matching the PRD §4 table and the SCAFFOLD `endpoints` list exactly.

## Hard constraints confirmed

- Storage is pure Python dicts. Grep for `sqlite3`, `open(`, `json.dump`, `pickle`, `shelve`, `/tmp` across all modules returns **zero hits**.
- Fresh import shows **0 rows across all 15 collections** and the logical clock at exactly `2026-08-01T00:00:00+00:00`. Nothing is seeded, preloaded, or hardcoded.
- Boots cleanly from a fresh process each invocation (no reloader, `threaded=False`), so `--isolation per-test-server` relaunches are safe.

## Boot + smoke verification

`bash start.sh` bound `0.0.0.0:10777` and answered `GET /nac/products` with HTTP 200. A 63-assertion end-to-end script passed **63/63**, walking the full business arc: operator/manufacturer/DC/product setup → contract with tier + coverage → submit → sign (plus 403 on wrong-operator sign) → deviation agreement with OCC (correct `ERR_STALE_CONTRACT_VERSION` on reuse of a consumed version) → submit/approve/activate → order line (list 1100 from 1000 cost at 10%, deviated invoice 900, extended 9000, zero fee in-market) → invoice (billback → ACCRUED) → clock advance → period close (compliance 100.00, rate 4.00, rebate 360 = 216 manufacturer / 144 distributor) → compliance report (shortfall −15.00) → settle → reverse-settlement (payable correctly restored) → bill-back claim (10 cases, 2000 cents) → submit → remittance 2500 (applied 2000, unapplied 500, claim + line RECOVERED, exposure 0) → reverse remittance (all counters and states exactly inverted) → pricing dispute → audit → `ERR_VARIANCE_BELOW_AUDIT_TOLERANCE` on an out-of-tolerance uphold → reject.

A separate negative-path script confirmed the auth and envelope contract: missing headers → 401 `ERR_UNAUTHENTICATED`, unrecognized role → 401 `ERR_UNAUTHENTICATED` (PRD §1 line 15), unauthorized role → 403 `ERR_UNAUTHORIZED`, duplicate code / unknown field / `limit=0` → 400 `ERR_INVALID_REQUEST`, unknown route → 404, and the list envelope carrying exactly `api_request_id` (24 chars, `req_` + 20 alnum), `api_request_timestamp`, `limit`, `offset`, `total_count`, `has_more` with `response_type: "array"`.

Two initial "failures" in that second script were errors in my test expectations, not the implementation — I verified both against the PRD: an unrecognized `X-User-Role` is specified as 401 `ERR_UNAUTHENTICATED` (not 403), and there is no `GET /nac/operators` collection endpoint in the spec, so 405 is correct.

The background server and temp scripts have been cleaned up; no `__pycache__` left behind.

## Step 7: Run Tests and Iterate — 2026-09-01T15:19:36.281Z

The whole task directory is untracked, so there's no baseline diff to show — but the edits I made were confined to 5 files. Final state: **95/95 passing in all 8 parallel rounds, zero skips.**

## Summary

**Iterations run:** 2 (sweep → diagnose/fix → sweep → clean)

**Failures found in iteration 1:** 5 tests, failing *identically and deterministically in all 8 rounds* (no flakiness anywhere in the suite — the parallel sweep confirmed stability rather than surfacing races).

**Tests deleted:** none. All 5 failures traced to verbatim PRD prose and survived both the coverage and unique-derivability checks, so all 5 were repaired rather than removed.

**Fixes applied to `test_suite/` (assertion layer — STEP 2, test was wrong):**

Four tests called the runner's `validate_success(resp)`, which defaults to `expected_status=200`, against endpoints that PRD §4 declares as creates: *"Operations that create a new resource return `201 Created`."* The PRD-faithful implementation correctly returned 201 and the tests rejected it. Corrected to `validate_success(..., 201)`:
- `test_13_validation_rules.py` — `TestStrandedAmendmentDraft`, both `open_contract_amendment` calls (`POST /nac/contracts/{id}/amendments` — "return the new draft contract").
- `test_14_endpoint_behaviors.py` — `TestLinkEndpointForeignKeys`, `create_substitution_rule`.
- `test_17_concurrency_versions.py` — `TestContractVersionToken`, `create_deviation_agreement`; and `TestDeviationVersionToken`, `create_bill_back_claim`.

Corroborating evidence this was the test bug and not an implementation bug: the suite *already* used the `validate_success(..., 201)` form for creates elsewhere (`test_08_interval_overlap.py:182` for `create_dc_coverage`, `test_10_entity_contracts.py:107` for `create_product`) — these four sites had simply omitted the argument.

**Fix applied to `implementation/` (STEP 3 — test was faithful):**
- `services/cascade.py`, `terminate_deviations()` + `clock_sweep()`: `terminate_deviations` now returns the ids it moved to `TERMINATED`, and `clock_sweep` extends `expired_deviation_ids` with them. Previously only window-expired agreements (`ACTIVE`/`PRICE_CEILING_BREACHED` past `effective_to`) were reported, so an agreement terminated by its contract's expiry cascade vanished from the response. PRD §3.3: *"the sweep reports what it touched through `expired_contract_ids` and `expired_deviation_ids`"* — the cascade-terminated row was touched. No double-reporting is possible, since a `TERMINATED` agreement no longer matches the window-expiry loop's state filter.

One judgement call worth flagging for your review: the clock-sweep fix rests on §3.3's *"reports what it touched"* rather than §2.5's narrower *"the rows the move swept into expiry."* A reader anchoring only on §2.5 could defensibly report just the window-expired agreements. I resolved in favour of §3.3 because it is the more specific sentence and sits immediately after the paragraph describing both effects, and because the same test independently asserts the cascaded agreement's status is `TERMINATED` — so the test's two halves are mutually consistent under only that one reading.

**Orchestrator note:** Step 7's cleanup removed the `results.*.json` files, so the orchestrator re-ran the identical 8-round parallel sweep at 2026-09-01T15:23Z as independent verification. Result: `results.{1..8}.json` all **95 / 95**, confirming the clean state and repopulating the per-round result files required by the output spec.

## Step 8: Finalize PRD — 2026-09-01T15:23:35.755Z

Done. `PRD_FINALIZED.md` written with 3 inline edits, no structural changes.

**Line counts:** PRD.md 447 → PRD_FINALIZED.md 447 (0.0% line delta; 3 of 447 lines revised in place, ~0.7% of lines touched).

**Changes**

- §4 (Endpoint Definitions preamble) — *revise* — pinned that an operation which both transitions the addressed resource and creates a new one (only `POST /nac/contracts/{contract_id}/amendments`) returns `201 Created` with the **new draft** in `data` — `implementation/routes/contracts.py:197`.
- §2.5 (Logical Clock) — *revise* — "the rows the move swept into expiry" → "the rows the move swept out of their live states, whose exact membership §3.3 pins", so the summary no longer contradicts the fact that cascade-`TERMINATED` agreements are reported too — `implementation/services/cascade.py:86`, `implementation/routes/reference.py:226-231`.
- §3.3 (Expiry) — *revise* — pinned list membership: `expired_contract_ids` = contracts this move drove to `EXPIRED`; `expired_deviation_ids` = every agreement the move drove out of a non-terminal state, i.e. both cascade-`TERMINATED` ones and window-`EXPIRED` ones, with no id reported twice — `implementation/services/cascade.py:42-50, 76-97`.

**Per-edit pre-edit search log**

1. **§4 status-code edit.** (a) Subject: HTTP status code and `data` payload of POST endpoints, specifically the create-plus-transition case. (b) Enumerated: grepped every `@bp.post` / `@bp.get` and every `return response.*` across all of `routes/` (`reference.py`, `contracts.py`, `deviations.py`, `notices.py`, `order_lines.py`, `rebates.py`, `billback.py`, `disputes.py`) plus `response.py:46,55` (`ok(status=200)`, `created`). Result: all 15 collection-root POSTs return 201; every sub-path action POST returns 200 (`submit-for-signature`, `sign`, `return-to-draft`, `suspend`, `reinstate`, `terminate`, `products/{id}/availability`, all deviation/notice/order-line/rebate/claim/remittance/dispute actions, `_clock/set_current_utc`, `compliance-report`); `contracts.py:197` is the unique 201-returning sub-path POST, and it serializes `draft`, not `parent`. Also checked other creates that mutate sibling rows (`billback.py:80` claim create → lines to `CLAIMED`; `billback.py:197` remittance → claims; `deviations.py:107` → parent contract version) to make sure the new clause could not be read as re-classifying them: they are collection-root creates already returning 201, and the clause is scoped to "the addressed contract"/the addressed resource. (c) Adjustment: worded the clause around the *addressed* resource being transitioned and named the amendment case explicitly, rather than a general "creates any row while mutating another" formulation, which would have been ambiguous for claim/remittance creates.
2. **§2.5 wording edit.** (a) Subject: the semantics of the clock endpoint's two returned id lists. (b) Enumerated: `routes/reference.py:220-231` (the only clock endpoint and only reader of `clock_sweep`), `services/cascade.py:76-97`, and all other `set_clock`/`clock()` uses via grep for `clock_sweep|expired_*_ids` — no second producer of either list exists. Confirmed the sweep also ends coverage rows (`end_coverages`) which are *not* reported. (c) Adjustment: replaced "into expiry" with the neutral "out of their live states" and deferred detail to §3.3 rather than restating membership twice; deliberately did not claim the lists cover every row the sweep touched (coverage rows are touched but unreported).
3. **§3.3 membership edit.** (a) Subject: which deviation-agreement and contract ids the clock sweep reports. (b) Enumerated every impl path that terminates or expires a deviation/contract: `cascade.terminate_deviations` (cascade.py:42, `DEVIATION_NON_TERMINAL` = the six states §3.3 already lists) and its two callers — `terminate_contract_cascade` (cascade.py:56, reached from `POST /contracts/{id}/terminate`, `routes/contracts.py:226-238`, which returns only the contract and reports no ids) and `clock_sweep` (cascade.py:86); plus `expire_parent_on_amendment_signature` (cascade.py:67-73, parent → `EXPIRED` on amendment signature, supersedes tiers and ends coverages, does *not* terminate deviations and reports nothing); plus the window-expiry loop (cascade.py:91-95) and the `PRICE_CEILING_BREACHED` producer (`notice_activation_cascade` hop 3, cascade.py:120) to confirm a breached agreement is still swept by the window loop. (c) Adjustment: scoped the sentence strictly to "this clock move"/"the same move" so it makes no claim about the person-driven terminate cascade or the amendment-signature expiry path (the latter notably does *not* terminate deviations in the impl — an off-scope divergence from §2.9 that I intentionally left untouched); also avoided asserting any ordering of ids within either list, since the impl's order (per-contract cascade groups first, then window-expired, in dict insertion order) is not something the PRD needs to fix and a false ordering claim would be a new mismatch.

## Step 9: Complete PRD — 2026-09-01T15:43:20.566Z

`workspace/PRD_COMPLETED.md` is written and complete.

**Deltas**
- Source `workspace/PRD_FINALIZED.md`: 447 lines / 98,718 chars
- Completed `workspace/PRD_COMPLETED.md`: 447 lines / 105,898 chars → **+7,180 chars, 0 line delta** (every change is an in-paragraph insert or clause revision; no new sections, no reordering)
- 28 lines/paragraphs touched, 33 discrete changes: **26 ambiguity-pins, 7 mismatch-revisions**

**Changes**
- §2.3 — insert — ambiguity — a non-integer `limit`/`offset` is `ERR_INVALID_REQUEST` alongside out-of-range values — `implementation/validation.py:196-206`
- §2.3 — revise — ambiguity — `created_at` ascending is tie-broken by insertion order — `implementation/db.py:78-80`
- §2.3 — insert — ambiguity — filters are exact equality, an out-of-enum filter value is `ERR_INVALID_REQUEST`, an id filter matching nothing returns an empty window — `implementation/routes/common.py:45-57`
- §2.4 — insert — mismatch — the one exception to "every mutation bumps `version`": claim create, `ManufacturerRep` dispute and the credit side branch recompute `open_claim_exposure_cents` without touching the manufacturer row; submit/write-off/apply/reverse do bump it — `implementation/routes/billback.py:78,140` vs `120-121,166-167`; `implementation/services/cascade.py:151`
- §2.5 — revise — ambiguity — the clock endpoint accepts any parseable instant, including one earlier than the current value, and sweeps against the new value — `implementation/routes/reference.py:220-228`
- §2.6 — revise — ambiguity — percentages travel as JSON numbers, so trailing zeros may be dropped — `implementation/response.py:30-31`
- §3.1 — insert — ambiguity — all six uniqueness constraints (`operator_code`, `manufacturer_code`, `dc_code`, `sku`, `contract_code`, scoped `remittance_reference`) reject duplicates with `ERR_INVALID_REQUEST` — `implementation/routes/common.py:36-42`
- §3.1 — revise — ambiguity — mapping a `SUSPENDED` DC is `ERR_INVALID_REQUEST`, judged with body fields — `implementation/routes/contracts.py:324`
- §3.1 — revise — mismatch — all three cost fields are mandatory at registration; `substitution_group_code` is optional but non-empty; the availability write accepts either field or neither and still bumps `version` — `implementation/routes/reference.py:134-136,139,206-214`
- §3.2 — revise — mismatch — `markup_value` is two-decimal in both modes; integrality is not enforced under `DOLLARS_PER_CASE`, the fractional cent is rounded half up at price formation — `implementation/validation.py:get_decimal(places=2)`, `implementation/services/pricing.py:list_price`
- §3.3 — insert — ambiguity — incomplete configuration on submit-for-signature is `ERR_CONTRACT_INVALID_STATE`, same code as the wrong from-state — `implementation/routes/contracts.py:105-113`
- §3.3 — revise — ambiguity — a non-`ACTIVE` operator on sign is `ERR_CONTRACT_INVALID_STATE`, and the parent-amending check precedes the operator-status test — `implementation/routes/contracts.py:136-146`
- §3.3 — revise — mismatch — an amendment draft takes fresh term **defaults** rather than inheriting the parent's, copies only `operator_id`/`rebate_funding_manufacturer_id`, starts with zeroed counters and null signature fields; a second open amendment is `ERR_CONTRACT_INVALID_STATE` — `implementation/routes/contracts.py:159-190`
- §3.3 — insert — ambiguity — reinstating past `effective_to` is `ERR_CONTRACT_INVALID_STATE` — `implementation/routes/contracts.py:217-219`
- §3.4 — revise — ambiguity — a resolved deviated price ≤ 0 is `ERR_INVALID_REQUEST` but, being derived, is judged right after the priority-12 tier check and so before overlap and ceiling — `implementation/routes/deviations.py:51-74`
- §3.4 — insert — mismatch — activation re-derives and persists `deviated_price_cents` for `COST_PLUS_PROTECTED` from the entry-band tier's current cost, silently keeping the stored price when no entry tier or cost exists; `FIXED_NET_PRICE` stays pinned — `implementation/routes/deviations.py:186-199`
- §3.5 — insert — ambiguity — a `DISCONTINUED` product is `ERR_INVALID_REQUEST`, ahead of the contract-active check — `implementation/routes/order_lines.py:38`
- §3.5 — insert — ambiguity — substitution candidates with no cost on the tier's basis are dropped silently, and when the primary list price is zero only a zero-priced substitute survives (gap `0.00`) — `implementation/services/pricing.py:272-281`
- §3.5 — revise — mismatch — reprice requires an `OPEN` period (`ERR_REBATE_PERIOD_INVALID_STATE`) checked before contract-active; it recomputes five money fields only, leaving `applied_tier_id`, `cost_basis_snapshot_cents`, `deviation_agreement_id` and `is_contracted_item` untouched, and the fee re-lookup can raise `ERR_DC_NOT_COVERED` — `implementation/routes/order_lines.py:166-174`, `implementation/services/pricing.py:reprice_line`
- §3.5 — revise — ambiguity — substitute ranking ties fall through `rank`, `created_at`, then insertion order — `implementation/services/pricing.py:287`
- §3.6 — revise — ambiguity — the missing-required-input half of the index/cost exclusivity fires immediately after priority 12 (before window/notice-period tests) while the forbidden-input half sits at priority 28 — `implementation/routes/notices.py:98,111`
- §3.6 — revise — ambiguity — a zero current cost makes `delta_pct` exactly `0.00`, hence a minor change — `implementation/routes/notices.py:61`
- §3.6 — insert ×3 — ambiguity — the activation cascade spans deviations on every contract, bumps `price_revision_count` unconditionally even when the re-derived price is unchanged, and reads the agreement's own entry-tier `cost_basis` with fallback to the notice basis (null cost keeps the price but still moves counters and `version`) — `implementation/services/cascade.py:110-121`, `implementation/services/pricing.py:rederive_deviated_price`
- §3.7 — revise — mismatch — close-period order is period state → contract status → `ERR_PERIOD_NOT_ENDED`, so a bad contract status is reported ahead of a period that has not ended — `implementation/routes/rebates.py:83-89`
- §3.8 — revise — ambiguity — a gathered line already `CLAIMED` keeps that status but is re-pointed at the new claim and version-bumped — `implementation/routes/billback.py:68-72`
- §3.8 — revise — ambiguity — `claimed_amount_cents < 1` on submit is `ERR_CLAIM_INVALID_STATE`, reported only after the manufacturer-suspension test — `implementation/routes/billback.py:108-112`
- §3.8 — revise — ambiguity — a written-off claim blocks remittance reversal with `ERR_CLAIM_INVALID_STATE`, tested after the remittance's own from-state — `implementation/routes/billback.py:222-228`
- §3.9 — revise+insert ×4 — mismatch — the retroactive audit still applies the prospective sweep's two filters (`pricing_status` in DRAFT_PRICED/INVOICED/REPRICED, `order_date ≥ effective_from`); with no `ACTIVE` tier it falls back to the line's `applied_tier_id` before raising `ERR_NO_TIER_FOR_PRODUCT_CLASS`; a line carrying `deviation_agreement_id` takes that agreement's current `deviated_price_cents` with no window re-check and skips the substitution branch; `variance_pct` is `0.00` when the invoiced price is zero — `implementation/routes/disputes.py:27-56`
- §3.9 — revise — ambiguity — resolve always writes `audit_note`, an omitted `note` writing null and clearing an earlier request-info note — `implementation/routes/disputes.py:159,170`
- §3.9 — revise ×2 — ambiguity — credit hop 2 carries `service_fee_cents` across untouched (the waiver threshold is never re-tested against the reduced extended value), and the side branch leaves a claim in any status other than `SUBMITTED` alone, `PARTIALLY_RECOVERED` included — `implementation/services/cascade.py:136-145`

Deliberately not pinned, as out of scope of the PRD's endpoint contract and against the minimal-change instruction: the `app.py` mapping of unknown routes to `ERR_INVALID_REQUEST` 404 and wrong methods to 405, and the minimum-1 range on `expected_contract_version` / `expected_deviation_agreement_version`.
