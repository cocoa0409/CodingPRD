# Worklog — task_1148_paint_store_contractor_account

## Step 1: Create Task Directory — 2026-08-11T00:00:00.000Z

Pre-assigned output folder `tasks/task_1148_paint_store_contractor_account` with `workspace/` subdirectory already exists (per headless run instructions). Step 1 treated as done; auto-index scan skipped as instructed.

## Step 2: Generate Scaffold — 2026-08-11T03:10:00.000Z

Scaffold generation complete. All three artifacts are on disk in `/home/ubuntu/github/CodingPRD/tasks/task_1148_paint_store_contractor_account/` and the skill's lint gate passes clean.

**Verdict block (verbatim, final run):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Design summary** (complexity profile: Pricing engine × Compliance/audit archetypes; flat FK topology; parallel state-machine shape; peer_roles; immediate consistency; layers: cascading side effects, dual-variant calculation, rate/threshold triggers, version-pinning on approval):

- **SCAFFOLD.yaml** (§1.0–§1.7, no design keys):
  - **Entities: 17** — ContractorAccount, JobAccount, Jurisdiction, VocRule, Product (self-FK replacement), TintFormula (versioned, self-FK supersede), ColorMatchRequest, ProductBulletin, SpecSheet (self-FK supersede), SpecLine, Order, OrderLine, ReturnRecord (append-only), Delivery, RebateStatement, LoyaltyTransaction (append-only), MistintListing
  - **State machines: 11** — including Order with parallel payment×fulfillment dimensions, cyclic ColorMatchRequest (revision loop, iteration cap 3), cyclic RebateStatement dispute loop, SpecSheet branching with cascade-driven NEEDS_REVISION
  - **Calculations: 12** — headliners: line_pricing (pinned per-unit-then-multiply rounding), rebate_provisional vs rebate_final (forward-looking projection/prorate vs chronological straddling marginal sweep with symmetric refund unwind), pull_through ordered vs delivered variants, mistint weekly decay with cost floor
  - **Validations: 41** (priority-ordered; VOC safety before referential, state before fiscal)
  - **Endpoints: 77** (flat, incl. `POST /_clock/set_current_utc` with fixed default 2026-05-01T00:00:00Z; every FK reverse-reachable)
  - **Errors: 41**; **Roles: 5** (Contractor is entity_backed:ContractorAccount, others opaque); **Concurrency rules: 2** (OCC on ContractorAccount.version for PATCH and POST /orders)
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml** (§1.8): **18 instances** — 2 per each of the 9 difficulty rules, all with literal-computed asserts (e.g. provisional rebate 174065 vs final 280000; unit-round-first 6293 vs extend-first 6294; cap-binds payable 1000000)
- **SCAFFOLD_CORNER_DESIGN.yaml** (§1.9): **43 instances** across all nine taxonomy sections — 38 with full structured test recipes (lint counts 38 scanned) plus 5 `excluded_because` stubs pointing at §1.8 instances

All formula-derived assert literals were pre-computed by executing the formulas in Python; grounds resolvability, instance-name uniqueness across both design files, stub-reference validity, and forbidden-vocabulary scans all pass with zero problems.

## Step 3: Copy Shared Files — 2026-08-11T03:11:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1148_paint_store_contractor_account/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-11T03:19:00.000Z

All checks pass. The PRD is complete and verified at `/home/ubuntu/github/CodingPRD/tasks/task_1148_paint_store_contractor_account/workspace/PRD.md`.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1148_paint_store_contractor_account/workspace/PRD.md` — 331 lines, 8,437 words.

**Section list:**
- §1. Introduction (2 paragraphs: business context + the two shaping forces — derived financials and the logical clock)
- §2. Global Specifications & System-Wide Principles: 2.1 Roles/RBAC, 2.2 API Response Structure (emitted verbatim byte-for-byte from `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 The Logical Clock, 2.5 Common Resource Properties, 2.6 Money/Rounding/Percentages, 2.7 OCC on the Contractor Account, 2.8 Validation Pipeline and Error Precedence, 2.9 State Machines/Cascades/Version Semantics, 2.10 Half-Open Time Windows
- §3. Business Logic & Workflows (9 subsections): 3.1 Contractor Accounts/Tier Evaluation, 3.2 Job Accounts/Budget Discipline, 3.3 Catalog Governance/Discontinuation, 3.4 Tint Formulas/Color-Match, 3.5 Spec Sheets/Pull-Through, 3.6 Order Capture/Pricing/Payment, 3.7 Returns/Refunds/Loyalty Ledger, 3.8 Delivery Operations, 3.9 Rebate Settlement/Mistint Recovery
- §4. Endpoint Definitions (4-column table, 77 rows — exact match to scaffold's 77 endpoints, methods+paths set-equal)
- §5. Error Code Catalogue (2-column table, 41 rows — exact match to scaffold's 41 errors, same order)

**Coverage audit (vs scaffold):**

Field coverage check (two passes run):
- entities[].fields: 91 required, 91 present, 0 missing
- endpoints[].request_body/input: 41 required, 41 present, 0 missing (incl. `expected_contractor_account_version`, `lines`, `reason`, `points_to_redeem`, `to_iso8601`)
- endpoints[].query_params: 19 required, 19 present, 0 missing
- nested `shots` fields (`colorant_code`, `ounces_128ths`): present
- Status: **PASS**

Rule coverage check:
- validation priority orderings: 41 validations expressed; global pipeline (§2.8 stages 1–9) plus explicit per-endpoint sequences for order-create (§3.6), returns (§3.7), dispatch (§3.8), request-revision state-before-cap (§3.4) — 0 missing
- concurrency_rules: 2/2 expressed with write operation + `expected_contractor_account_version` + `ERR_STALE_VERSION`/412, no time-overlap framing
- state machine transitions: all 12 machines, every transition from/to/precondition/side-effect expressed (incl. bulletin 4-hop cascade, return refund→clawback cascade, delivery bubble-ups, spec supersede/NEEDS_REVISION hop-3)
- calculations: 12/12 in precise reconstructible prose (pinned rounding orders, floors before multiply, tie-break "id never used", half-open windows, inclusive tier boundaries, 0.90 weekly decay with 25% floor)
- validations→error_id: all 41 matchable in §2/§3 narrative; every error ID appears outside the §5 table
- endpoints[].side_effects / applies_to: all expressed; multi-endpoint scopes (e.g. `ERR_ACCOUNT_SUSPENDED` on 4 endpoints, `ERR_JOB_NOT_OPEN` on 3) enumerated
- entities[].fields structured content: defaults/initials reconstructible (null-until-stamped fields, `adjustment_cents` zero, `returned_quantity` zero-start, `supersedes_formula_id` null for revision 1, `common_fields: false` pair limited to `id`+`created_at`)
- sibling-branch symmetry: proposals from both source states, 3 abandon branches, 2 refund-arrival paths, 2 revise paths, ordered/delivered pull-through variants, provisional/final rebate variants — all equal density
- Status: **PASS**

Path purity check (§3 only): 575 backtick tokens scanned; 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos — **PASS**

Additional checks: §2.2 verbatim block byte-identical; all 46 enum/state values present as exact UPPERCASE strings; 5 role names exact with `identity` translations (4 opaque, Contractor entity-backed); no operator-syntax leaks in prose; no fuzzy/approximating words; PRD.md ends at §5 with no audit footer.

## Step 5: Generate Unit Tests — 2026-08-11T03:45:00.000Z

Generation complete and verified. Summary:

## Files written

**test_helpers/ (9 files, all py_compile-clean and importable):**
- `types.py` — 18 entity TypedDicts + 16 status/role enums; append-only entities (ReturnRecord, LoyaltyTransaction) correctly omit `updated_at`/`version` per PRD §2.5
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~60 methods)
- `api_errors.py` — `ApiErrorId` enum (42 codes) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` plus ledger/append-only invariants
- `factories.py` — payload factories with unique-sequence defaults
- `constants.py` — tier thresholds, rebate bands, tax rate, mistint decay constants
- `test_users.py` — `TEST_USERS` for the four opaque roles + `make_contractor_headers(user_id)` for the entity-backed Contractor role
- `fixtures.py` — composite setup helpers (account/job/product chains, order pay/dispatch/deliver lifecycle, spec approval, bulletin publish, match proposals, tier targeting)
- `__init__.py` — barrel export

**test_suite/ (19 files: conftest.py + 18 test files, 89 test functions).**

## Queue A (difficulty, 18 instances) — translated 18/18, skipped 0
Every instance has exactly 2 tests (36 tests). All passed the PRD-first filter: both priority-pair instances rest on explicit PRD precedence text (§2.8 "the first failing check wins", §2.8 stage-8-before-stage-9, §2.8 family ordering, §3.6's per-endpoint fixed sequence), so they were adjudicated legitimate rather than silence-pattern skips. All pre-computed literal values (174065/280000, 899/6293, 1,000,000 cap, 2500 mistint floor, 600 balance, etc.) were independently recomputed and match.

## Queue B (corner, 43 instances) — translated 38/38 non-stub, 5 stubs excluded by design
- Non-stub instances: 38, each with ≥1 test (53 tests)
- Stubs not translated (cross-references verified to resolve): `rebate_provisional_projection_math` → rebate_provisional_vs_final_divergence; `bulletin_cascade_chain_coverage` → bulletin_effect_discontinuation_chain; `return_clawback_chain_coverage` → return_refund_loyalty_clawback_chain; `every_catalog_error_is_triggerable` → suspended_account_beats_credit_limit; `version_pinning_blocks_discontinued_on_new_lines` → spec_approve_blocked_by_discontinued_product
- For `append_only_ledger_has_no_version`, the "no update endpoint exists" claim was dropped (absence is not PRD-derivable); the asserted shape ("carry only `id` and `created_at` — both `updated_at` and `version` are absent") is verbatim PRD §2.5

## Verification results
- All 27 files pass `python -m py_compile`; `test_helpers` and `test_suite.conftest` import cleanly
- Tag audit: 89/89 test functions carry exactly one tail-anchored `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line; every tag resolves to a real non-stub instance; no tag points at an excluded stub; queue-A ≥2 and queue-B ≥1 coverage targets both met
- Citation audit: 116 quoted docstring citations, 100% survive whitespace-normalized literal grep of PRD.md
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold references in comments or docstrings

## Step 6: Generate Implementation — 2026-08-11T03:45:00.000Z

All verification complete. Here is the summary.

## Implementation Summary — task_1148_paint_store_contractor_account

**Location:** `/home/ubuntu/github/CodingPRD/tasks/task_1148_paint_store_contractor_account/workspace/implementation/`

### Files (23 total, 3,194 lines)
| File | Lines | Role |
|---|---|---|
| `start.sh` | 9 | Executable launcher; guarded `pip install` (no-op when flask present), `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.2,<4` |
| `app.py` | 56 | App assembly, global request lock, envelope'd error handlers, `0.0.0.0:$PORT` (default 10000) |
| `db.py` | 51 | In-memory dicts (17 stores), logical clock pinned at `2026-05-01T00:00:00Z`, UUID/seq generators |
| `errors.py` | 57 | `ApiError` + all 41 catalog error IDs with HTTP statuses |
| `envelope.py` | 38 | `meta`/`response_type`/`data` envelope; pagination fields in meta; error body shape |
| `util.py` | 44 | ISO 8601 UTC parse/format (3 fractional digits, `Z` suffix) |
| `validate.py` | 164 | Stage-6 shape validators, shots validator, `limit`/`offset` parsing (default 10, min 1, max 100), enum query-filter validation |
| `authz.py` | 87 | Stage 1-3: `X-User-ID`/`X-User-Role` auth, 5-role RBAC, Contractor ownership via direct/JobAccount/Order/RebateStatement/ColorMatchRequest chains, list scoping |
| `calc.py` | 186 | All calculation constants and formulas (Decimal, pinned round-half-up steps) |
| `services.py` | 400 | Derived fields (outstanding, ytd volume, spent, pull-through, balances), VOC lookup, rebate event stream, cascades |
| `serializers.py` | 264 | Per-entity serializers; computed fields derived at read; ledger rows without `version`/`updated_at` |
| `routes/` (10 modules) | 1,851 | accounts, jobs, catalog (jurisdictions/voc-rules/products/formulas/bulletins), colormatch, orders (+lines/returns), deliveries, specs (+lines), rebates (+loyalty), mistint, clock |

### Endpoints: 77/77 registered
Route audit (method, path) against SCAFFOLD.yaml: zero missing, zero extra (Flask's built-in `/static` route disabled).

### State machines implemented (11)
ContractorAccount (ACTIVE⇄SUSPENDED), JobAccount (OPEN/ON_HOLD/COMPLETE with open-work guard), Product (ACTIVE→DISCONTINUED via bulletin), TintFormula (supersede/retire/cascade/withdrawal), ColorMatchRequest (SUBMITTED→PROPOSED→APPROVED/REVISION_REQUESTED/ABANDONED, 3-iteration cap), ProductBulletin (DRAFT→PUBLISHED→EFFECTIVE with 4-hop cascade: product → formulas → spec lines → APPROVED sheets to NEEDS_REVISION), SpecSheet (DRAFT/SUBMITTED/APPROVED/REJECTED/NEEDS_REVISION/SUPERSEDED with single-approval-per-project supersede), Order (parallel payment UNPAID/PAID/PARTIALLY_REFUNDED/REFUNDED × fulfillment PENDING/OUT_FOR_DELIVERY/DELIVERED/CANCELLED), Delivery (SCHEDULED→EN_ROUTE→DELIVERED/FAILED, terminal FAILED with re-delivery-as-new-row), RebateStatement (ACCRUED→FINALIZED⇄DISPUTED→PAID), MistintListing (LISTED→SOLD/WRITTEN_OFF).

### Calculations implemented (11)
line_pricing (per-unit round-half-up first, tier 0/5/10/15% + 3% qty break ≥10), order_totals (order-level 8.25% tax, pinned lines→subtotal→tax→total), tier_evaluation (inclusive 5M/15M/40M thresholds on YTD net volume), rebate_provisional (annualize→band→prorate, two pinned floors), rebate_final (chronological marginal band-fill/peel, payments-before-refunds tie-break, single final rounding), rebate_payable (min/max waterfall with 5% cap and zero floor), loyalty_accrual/clawback (floor-then-multiply, 1/2/3/5× by tier snapshot), return_refund (per-event tax rounding, no restocking fee), job_spent, pull_through (ordered vs delivered variants, 2-decimal round-half-up), mistint_price (0.90^weeks decay with 25% cost floor).

### Validations / error catalog
All 41 errors with exact IDs/statuses; 9-stage pipeline order enforced (auth → RBAC → ownership → path existence → body refs → shape → OCC → state → business[safety→temporal→constraint→referential→fiscal]). OCC via `expected_contractor_account_version` (412) on account PATCH and order create; account version bumps on order create/pay/cancel, return cascades, tier change, rebate payout, and direct mutations.

### Storage
Pure in-memory dicts; no seeding (grep audit clean), no disk persistence. Verified empirically: entity created in boot 1 returns 404 `ERR_NOT_FOUND` in boot 2, and the logical clock resets to `2026-05-01T00:00:00Z`.

### Verification results
- `python -m py_compile`: all 21 Python files pass.
- `start.sh` executable (`rwxrwxr-x`), reads `$PORT`, binds `0.0.0.0`, foreground via `exec`.
- Smoke boot: server answers within ~1.5s; 401-without-headers, 201 account create, 200 read, enveloped 404 on unknown route, 204 clock set — all correct.
- Two end-to-end exercises (60+ assertions) passed against live boots: pricing/tax arithmetic, OCC 412, VOC limit, loyalty earn/clawback balances, pull-through ordered/delivered divergence, delivery buffer 30-min rule, dispatch VOC re-check, fail→re-deliver flow, rebate provisional/final/period-net/payable figures (provisional 393 vs final 394 — dual-variant divergence confirmed), dispute→resolve→pay, mistint decay, bulletin cascade, spec supersede, iteration exhaustion, suspended-account blocks, credit/budget caps, custom-tint no-return, per-event refund rounding (full-quantity return staying PARTIALLY_REFUNDED per the pinned per-event tax rule), pagination meta, contractor list scoping, and ownership 403s.

**Orchestrator cross-check (post-Step 6):** Flask url_map diff vs SCAFFOLD.yaml endpoints — scaffold 77, impl 77, missing [], extra [].

## Step 7: Run Tests and Iterate — 2026-08-11T03:52:00.000Z

All 8 rounds pass 89/89. The loop exits clean.

**Summary**

- **Iterations run:** 2 (sweep 1 surfaced one deterministic failure — identical in all 8 rounds; sweep 2 confirmed the fix across all 8 parallel rounds, 89/89 each).

- **Tests deleted:** none. The single failing test's rule is verbatim-covered by PRD §3.1 (tier thresholds), §3.6 (tier discount at line pricing), and §3.7 (earn formula keyed off `subtotal_cents`), and the expected outcome is uniquely derivable — so deletion was not warranted.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1148_paint_store_contractor_account/test_suite/test_13_mistint_and_loyalty.py` — `test_platinum_tier_earns_five_x_points`: corrected the expected loyalty math. The test expected `floor(10000/100) * 5 = 500` points and a 400,500 balance, ignoring that PRD §3.6's 15% PLATINUM tier discount prices the 10,000-list line to an 8,500 `subtotal_cents`, and PRD §3.7 computes the EARN entry from the discounted subtotal: `floor(8500/100) * 5 = 85 * 5 = 425` → balance 400,425 (exactly what the implementation returned in all 8 rounds of sweep 1). Also added an intermediate `subtotal_cents == 8500` assertion and updated the docstring narrative so the test now expresses the PRD rule faithfully rather than approximating it.

- **Fixes applied to `test_helpers/`:** none — fixtures, factories, and role-header builders were all PRD-consistent.

- **Fixes applied to `implementation/`:** none — the implementation in `/home/ubuntu/github/CodingPRD/tasks/task_1148_paint_store_contractor_account/workspace/implementation/` was already PRD-faithful; no endpoint, field, or check was added, removed, or weakened.

**Orchestrator verification (post-Step 7):** all 8 `results.{1..8}.json` present on disk; each reports passed=89 total=89 failed=0 errors=0. ALL-PASS.

## Step 8: Finalize PRD — 2026-08-11T03:53:00.000Z

Both files confirmed byte-identical, and the investigation is complete. No edits are warranted.

## Summary

**PRD.md vs PRD_FINALIZED.md:** both 330 lines / 60,320 bytes; 0% delta. `PRD_FINALIZED.md` is **byte-identical** to `PRD.md` (verified with `cmp`).

**Zero edits — explicit rationale:**

The single Step 7 item (`test_suite/test_13_mistint_and_loyalty.py::test_platinum_tier_earns_five_x_points`) was a pure test-expectation correction toward behavior that PRD.md already uniquely determines. The loyalty EARN base is pinned by an unambiguous two-step chain of defined terms:

1. PRD §3.6 defines the discounted subtotal (PRD.md line 166, verbatim): *"`subtotal_cents` is the sum of `line_total_cents` over all lines."* — where `line_total_cents` is itself pinned at line 164 as the tier-and-quantity-discounted, per-unit-rounded unit price times quantity, with the tier discount *"0% for `STANDARD`, 5% for `SILVER`, 10% for `GOLD`, and 15% for `PLATINUM`."*
2. PRD §3.7 then pins the EARN base to that defined term (PRD.md line 178, verbatim): *"the posted `EARN` entry's `points_delta` is the whole dollars of merchandise — the order's `subtotal_cents` divided by 100 and truncated down — multiplied by the tier multiplier from the order's `tier_snapshot`, which is 1 for `STANDARD`, 2 for `SILVER`, 3 for `GOLD`, and 5 for `PLATINUM`; the floor is taken before the multiplication."*

Because `subtotal_cents` is a PRD-defined term (not raw list price), the 10,000-cent PLATINUM line admits exactly one computation: `unit_price = round_half_up(10000 × 0.85) = 8500` → `subtotal_cents = 8500` → `EARN = floor(8500/100) × 5 = 425` → balance 400,425 — precisely what the implementation returned in all 8 sweep rounds.

**Implementation conformance at the Step 7 site** (no mismatch, so nothing to pin):
- `/home/ubuntu/github/CodingPRD/tasks/task_1148_paint_store_contractor_account/workspace/implementation/services.py:238-243` — `post_earn(order)` calls `earn_points(order["tier_snapshot"], order["subtotal_cents"])`; EARN keys off the order's discounted subtotal and the frozen tier snapshot.
- `/home/ubuntu/github/CodingPRD/tasks/task_1148_paint_store_contractor_account/workspace/implementation/calc.py:155-157` — `earn_points` = `(subtotal_cents // 100) * TIER_POINT_MULT[tier_snapshot]`; floor before multiplication, matching §3.7 verbatim.

**Per-edit pre-edit search log:** not applicable — no edits were committed, so no search was triggered. The verification reads above (PRD §3.6/§3.7, `services.py:238-251`, `calc.py:155-161`, and the corrected test at `test_suite/test_13_mistint_and_loyalty.py:115-162`) served only to confirm the PRD already uniquely determines the Step 7 behavior.

## Step 9: Complete PRD — 2026-08-11T04:04:00.000Z

The diff is exactly 16 single-paragraph hunks, all intended. The deliverable is complete.

## Summary

**Source vs output**: `PRD_FINALIZED.md` (identical to `PRD.md`) → `PRD_COMPLETED.md`, both 330 lines; char count 60,320 → 63,401 (+3,081). All changes are in-paragraph inserts/revisions; no new sections, no new paragraphs.

**Counts**: 18 ambiguity-pins, 2 mismatch-revisions (20 logical changes across 16 edited paragraphs).

**Changes** (all impl paths under `/home/ubuntu/github/CodingPRD/tasks/task_1148_paint_store_contractor_account/workspace/implementation/`):

- §2.1 — insert — ambiguity — create endpoints whose body names `contractor_account_id` (job, order, redemption) use it as the ownership anchor for `Contractor` callers — routes/jobs.py:31-34, routes/orders.py:52-55, routes/rebates.py:162-164
- §2.1 — insert — ambiguity — contractor list scoping: implicit restriction to owned rows; a filter naming another contractor's account/existing resource → `ERR_NOT_RESOURCE_OWNER`; a filter naming a nonexistent resource just narrows the page — authz.py:76-87, routes/orders.py:242-244,301-307,355-363, routes/deliveries.py:94-108, routes/rebates.py:193-197
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_VALIDATION` (400) — validate.py:127-153
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion sequence — serializers.py:261-264
- §2.4 — insert — ambiguity — clock may be set earlier or later; no monotonicity enforced — routes/clock.py:11-18, db.py:38-40
- §2.5 — insert — ambiguity — at creation `version` is 1 and `updated_at` equals `created_at` — services.py:19-26
- §2.8 stage 5 — insert — ambiguity — multiple body foreign keys resolve in the order the endpoint's §3 narrative names them — routes/orders.py:58-78, routes/deliveries.py:36-41, routes/catalog.py:245-250
- §3.1 — revise — mismatch — `outstanding_balance_cents` excludes `CANCELLED` orders (PRD's literal "payment_status UNPAID" formula would count them, since cancel leaves payment `UNPAID`) — services.py:72-78, routes/orders.py:281
- §3.1 — revise — ambiguity — ytd volume window pinned to paid_at ≥ Jan 1 of clock's current year and ≤ current clock instant — services.py:89-99
- §3.4 — insert — ambiguity — proposal endpoint answers HTTP 201 with the updated request (not the new formula) in `data` — routes/colormatch.py:100
- §3.5 — insert — ambiguity — revision preserves `approved_at` and `supersedes_spec_sheet_id` unchanged — routes/specs.py:181-188
- §3.6 — insert — ambiguity — `lines` may be empty; the order then prices to zero subtotal/tax/total — routes/orders.py:86-107,166-179
- §3.6 — insert — ambiguity — cancellation leaves `payment_status` `UNPAID` — routes/orders.py:278-286
- §3.7 — revise — mismatch — order becomes `REFUNDED` when `refunded_cents` reaches **or exceeds** `total_cents` (per-event tax rounding can overshoot); PRD said "exactly" — services.py:350-354
- §3.9 — insert — ambiguity — provisional amount is 0 when the period spans <1 whole day or zero whole days elapsed — calc.py:99-100, services.py:186-191
- §3.9 — revise — ambiguity — final event stream: ties remaining after the `created_at` tiebreak break by row insertion order — services.py:203,212-214
- §3.9 — insert — ambiguity — resolve-dispute replaces `adjustment_cents` outright, not accumulates — routes/rebates.py:132-136
- §3.9 — insert — ambiguity — mark-sold: non-string or unresolvable `sold_to_contractor_account_id` → `ERR_REFERENCE_NOT_FOUND` (422) — routes/mistint.py:92-99
- §4 — insert — ambiguity — enum-typed filter values outside the enum → `ERR_VALIDATION` (400) — validate.py:156-164
- §4 — insert — ambiguity — undefined paths → `ERR_NOT_FOUND` (404) regardless of headers; unsupported method on a defined path → same error id at 405 — app.py:35-42

Everything else walked (all 10 route modules, calc.py, services.py, serializers.py, validate.py, authz.py, envelope.py) matched PRD prose already: endpoint/role matrix, pipeline stage ordering per endpoint, all calculation formulas and rounding points, cascade hops and version bumps, serializer field sets, error catalog, and the §4 filter list required no changes.

**Orchestrator verification (post-Step 9):** `workspace/PRD_COMPLETED.md` present on disk (330 lines, 63,401 bytes). Step 9 edited documentation only — no implementation or test artifacts changed after Step 7's final clean 8-round sweep (89/89 × 8).
