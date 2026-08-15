# Worklog — task_1745_manufactured_modular_home_dealer

## Step 1: Create Task Directory — 2026-08-14T12:56:00.000Z

Task directory `tasks/task_1745_manufactured_modular_home_dealer/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per instructions; no index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-14T14:09:00.000Z

All checks pass. The scaffold package is complete and verified.

## Summary

Generated the scaffold for `task_1745_manufactured_modular_home_dealer` (Manufactured & Modular Home Dealer) from the verbatim scenario, with no reference to sibling tasks. All three artifacts are in `/home/ubuntu/github/CodingPRD/tasks/task_1745_manufactured_modular_home_dealer/`:

**Counts**
- Entities: 15 (HomeModel, Community, Lot, Customer, HomeUnit, SalesOrder, OrderOption, SiteEvaluation, FinancingApplication, TransportCrew, TransportJob, TitleRecord, WarrantyClaim, TradeInAppraisal, DelayNotice)
- State machines: 11 declared (SalesOrder carries two — deal_status pipeline with reconfiguration revert + parallel payment_status dimension; cyclic machines on WarrantyClaim (review/appeal loops), TransportJob (SCHEDULED↔DELAYED), TradeInAppraisal (counter-offer supersession), HomeUnit (retail resale loop))
- Calculations: 10 (per-line discount rounding, pinned-circular doc fee, multi-input transport quote, escort threshold, dual-variant loan payment, dual-variant trade-in credit, dual-anchor warranty window, delay compensation, crew day-capacity, lot fit)
- Validations: 33 (ordered: auth → ownership → existence → OCC → state → safety → constraint → temporal → referential → fiscal)
- Endpoints: 76 (incl. `POST /api/_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default)
- Errors: 43 (14 domain-specific 404s, plus OCC 412, SoD 403, and boundary-specific fiscal/temporal/safety codes)
- Roles: 9 (Customer is entity-backed; segregation-of-duties between SalesConsultant/LenderAgent/Appraiser, plus reviewer≠resolver on warranty claims)
- Difficulty instances: 25 (all 9 rules; 3 rules carry a third instance; every rule's differentiation clause is exercised — e.g., modes (a)+(b)+(c) for combinatorial formulas, three distinct error-category pairs for priority conflicts)
- Corner instances: 62 (58 real + 4 excluded stubs), spanning all nine claim-taxonomy sections; 1,151 structured API calls total across both design files

**Verification**
- `scaffold_lint.py` verdict: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (one FK reverse-reachability violation found and fixed during iteration)
- All formula-derived assertions are precomputed literals (verified by executing the formulas in Python: canonical order total 9,471,997 with the pinned 143,102 per-line discount vs 143,101 whole-subtotal trap; annuity payments 67,297/54,915/71,121; transport quotes 301,200/65,000; delay compensations 0/7,500/37,500/75,000)
- Zero unbound `${var}` placeholders; zero duplicate instance names across both files; zero forbidden concurrency vocabulary; OCC version inputs always reference captured versions

**Notable design decisions**
- Transport booking gates on FINANCING_APPROVED (not post-funding) so the cancel-cascade difficulty instance can exercise job→crew capacity restoration — funded orders are deliberately uncancellable (`ERR_ORDER_NOT_CANCELLABLE`)
- Two true OCC races only (financing-application and site-evaluation create-with-supersede on `SalesOrder.version`); look-alike conflicts (lot reservation, double-cancel) were classified as state preconditions per §1.2.1's filter
- Real-property deadlock avoided: funding requires a type-matching ISSUED title, conversion to real property happens post-install; REAL_PROPERTY is forbidden on community lots
- Trade-in acceptance cascade (appraisal→order→active application recompute) and delay cascade (job→DelayNotice→order compensation aggregate) are the depth-3 chains; the order-cancel cascade carries the second trigger family
- Logical clock drives warranty windows (inclusive final-day boundary), 14-day rate locks, factory lead times, and schedule-in-past checks, keeping every temporal test wall-clock independent

## Step 3: Copy Shared Files — 2026-08-14T14:10:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_1745_manufactured_modular_home_dealer/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T14:35:00.000Z

All audits pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1745_manufactured_modular_home_dealer/workspace/PRD.md`.

## Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1745_manufactured_modular_home_dealer/workspace/PRD.md` — 373 lines.

### PRD section list
- **§1 Introduction** (3 paragraphs: business context, segregation-of-duties pain points, engineering constraints)
- **§2 Global Specifications** — 2.1 RBAC (9 roles, per-role `identity:` prose incl. entity-backed `Customer` and the `SiteEvaluator` evaluator_id exception), 2.2 API Response Structure (byte-identical verbatim block), 2.3 Pagination & Result Filtering, 2.4 The Logical Clock, 2.5 Resource Identity/Timestamps/Versioning (incl. `DelayNotice` carrying only `id`/`created_at`), 2.6 Money/Precision/Rounding, 2.7 Optimistic Concurrency on Order-Scoped Writes, 2.8 Request Validation Pipeline (all 33 priority layers, ordered, each with error id + HTTP status + full applies_to endpoint list), 2.9 Two Dimensions of Order State, 2.10 Cascades/Compensation/Bubble-Up
- **§3 Business Logic & Workflows** — 3.1 Catalog/Communities/Lots, 3.2 Buyers & Inventory, 3.3 Orders/Options/Pricing, 3.4 Confirm/Site Evaluation/Cancel Cascade, 3.5 Financing, 3.6 Transport (crews, escorts, capacity, quote, delays, delivery, set), 3.7 Titling & Closure, 3.8 Warranty, 3.9 Trade-Ins
- **§4 Endpoint Definitions** — 76 rows, 4 columns (Method/Path/Description/Roles); every role list verified equal to the scaffold's
- **§5 Error Code Catalogue** — 43 rows, 2 columns (ID, HTTP status)

### Hard-contract audit results
- **Contract 1 (Field-Name Coverage): PASS** — entity fields 102/102, request-body fields 72/72, query params 13/13, zero missing (verified mechanically; two passes run — first caught only a tooling artifact from un-stripped code fences, plus two genuinely missing enum literals `ACCEPT`/`DECLINE`, which were added to §3.9).
- **Contract 2 (Rule Coverage): PASS** — validations with priority: 33/33 expressed in §2.8 in order; OCC rules: 2/2 (both write endpoints, `expected_sales_order_version`, `ERR_STALE_VERSION`/412, no race-framing); state-machine transitions: all 11 machines covered (including the financing self-loop, the six cancel branches with the full compensation cascade, the `SET_COMPLETE`→`TITLED` chained auto-transition, lazy `EXPIRED` on fund breach); calculations: 10/10 in precise prose with all constants (per-line discount rounding pinned with the forbidden whole-subtotal variant called out, doc-fee circularity broken via discounted-subtotal base, half-open crew windows with adjacency, inclusive warranty windows); validation conditions and applies_to scopes enumerated; sibling branches (decide/review/resubmit/cancel/supersede) rendered at equal density.
- **Contract 3 (§3 Path Purity): PASS** — 620 backtick tokens scanned in §3, 0 path tokens, 0 bare HTTP methods, 0 method+path combos.
- §2.2 verified **byte-identical** to `section-2.2-response-structure.md`.

### Zero-silence decisions (scaffold ambiguities resolved without inventing rules)
1. **No discontinue/deactivate endpoints exist** for `HomeModel`/`Customer` — the PRD states the `DISCONTINUED`/`INACTIVE` enum values, creation defaults, and the "DISCONTINUED models cannot back new units" rule without inventing lifecycle endpoints or nominating an error id the scaffold doesn't declare.
2. **Warranty unit-state gate duality** — the entity field says claims require `ON_SITE`/`INSTALLED` while the coverage calc gates `TRANSPORT_DAMAGE` on `IN_TRANSIT`/`ON_SITE`; rendered as complementary per-claim-type gates rather than picking one.
3. **`REAL_PROPERTY` title gate at funding** (requires an `ISSUED` `REAL_PROPERTY_AFFIXED` record even though conversion requires `INSTALLED`) — reported exactly as scaffolded; the path exists because title-record creation accepts `title_type` directly.
4. **AWAITING_DELIVERY cancel symmetry note** — the scaffold's remark that this guard is practically unreachable (funding sets `FINANCED`) was folded into the general cancel-guard statement rather than calling out implementation trivia.

## Step 5: Generate Unit Tests — 2026-08-14T15:30:00.000Z

Generation complete. All outputs are in the task directory.

## test_helpers/ (9 files)
- `/home/ubuntu/github/CodingPRD/tasks/task_1745_manufactured_modular_home_dealer/test_helpers/types.py` — 15 entity TypedDicts + 19 status/role enums; `DelayNotice` carries only `id`/`created_at` (PRD §2.5 append-only exemption)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (70+ methods), module-level `api_client`
- `api_errors.py` — all 44 error IDs with HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions, `assert_instant_equals` (second-precision instant compare, PRD §2.6), `assert_booked_dates` (date-normalized), `assert_order_money_conservation`
- `factories.py`, `constants.py` (pricing tiers, fee clamp, quote/escort/delay/warranty/trade-in constants, canonical order figures)
- `test_users.py` — `TEST_USERS` for 9 roles + `make_customer_headers` (entity-backed identity threading), evaluator/service-manager builders
- `fixtures.py` — composite scenario builders: `new_order_scenario`, `canonical_community_scenario`, progression tiers (`confirm_order` → `schedule_evaluation` → `record_findings` → `approve_evaluation` → `create_application` → `submit_application` → `decide_application` → `issue_title_for_order` → `fund_application` → `book_transport` → `progress_to_delivered/installed`), trade-in chain; OCC-guarded creates always re-read the order version

## test_suite/ (conftest.py + 10 files, 106 tests)
test_01 catalog/inventory/lots (11), test_02 envelope/auth/RBAC (6), test_03 pricing (9), test_04 order lifecycle (13), test_05 site evaluations (9), test_06 financing (16), test_07 transport booking (15), test_08 delivery/delay/titles (9), test_09 warranty (9), test_10 trade-in (9).

## Queue A (difficulty): 48 tests emitted over 24 instances, 1 skipped
- Skipped: `cross_entity_state_dependency/warranty_claim_requires_unit_on_site_or_installed` — **PRD contradiction + silence**: it asserts `ERR_INVALID_STATE` for a TRANSPORT_DAMAGE claim on an INSTALLED unit, but PRD §2.8 rule 25 pins the transport-damage state gate to `ERR_WARRANTY_EXPIRED`; and the RESERVED-unit rejection error ID is named nowhere in the PRD. Fails unique derivability — no test emitted.

## Queue B (corner): 58 tests emitted over 58 non-stub instances, 0 skipped
- 4 `excluded_because:` stubs not translated; all their `difficulty_instance` cross-references verified to resolve (money_conservation_across_trade_cycle, crew_halfopen_weighted_window, order_cancel_depth3_cascade, chattel_vs_real_property_monthly_payment).

## Stage 2 self-check results (all green)
- `python -m py_compile` on all 21 files: OK; `pytest --collect-only`: **106 tests collected**, no import/fixture errors
- Tag audit: every test has exactly one `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` as the final docstring line; all 106 tags resolve to real instances; difficulty coverage 24/24 instances × ≥2; corner coverage 58/58 × ≥1
- Citation audit: every docstring carries `PRD §` quotes; each quoted span is ≥8 words and survives whitespace-normalized literal substring match against PRD.md (30 initial failures — markdown bold labels, `...` abbreviations, fused quotes — all fixed; final pass clean)
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no "scaffold" references in generated code; literal expected values copied verbatim from the design indices (e.g., discount 143,102 vs forbidden 143,101; doc fee 59,100 vs circular 59,691; estimates 67,297/54,915; quotes 301,200/65,000/20,000)

## Step 6: Generate Implementation — 2026-08-14T15:30:00.000Z

Implementation complete and verified. Summary:

## File list — `workspace/implementation/`

- `start.sh` — foreground launcher: `cd` to script dir, guarded install (`pip install` only if `import flask` fails, so per-test reboots are no-ops), `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask
- `app.py` — Flask app factory, ApiError/404/405/500 handlers, blueprint registration, entry point
- `db.py` — in-memory `Store` (15 entity dicts keyed by id), monotonic `_seq`, logical-clock timestamps, `create_record`/`bump` (version+1, updated_at refresh). **Store starts empty; no seeding anywhere**
- `clock.py` — logical clock, startup default exactly `2026-08-01T00:00:00Z`, never wall-clock
- `errors.py` — `ApiError` + full 42-entry error catalog with scaffold HTTP statuses
- `response.py` — exact envelope: `meta.api_request_id` (`req_…`), `api_request_timestamp` (ISO-8601 UTC, 3 fractional digits), `response_type` object/array/error, `data`; list meta adds `limit/offset/total_count/has_more`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401 `ERR_UNAUTHENTICATED`, 403 `ERR_UNAUTHORIZED`), 9 declared roles
- `validate.py` — `Shape` field-shape validator (deferred to priority 33), ISO datetime parsing, pagination params (limit 1–100 default 10, offset ≥ 0)
- `calc.py` — all 10 calculations with `Decimal` round-half-up
- `services.py` — cross-entity recomputes, bubble-ups, cascades
- `routes/` — 11 blueprints: `catalog` (models/communities/lots), `customers`, `units`, `orders` (+options/confirm/cancel/close), `evaluations`, `financing`, `transport` (crews/jobs/delay-notices), `titles`, `warranty`, `tradein`, `clock_route`

## Endpoint count

**76 routes** — matches the endpoint table exactly (1 clock + all CRUD/actions).

## Organization of the hard parts

- **State machines**: enforced per handler at priority 7 (`ERR_INVALID_STATE`), with the cancellation guard at priority 8 (`ERR_ORDER_NOT_CANCELLABLE` covers TITLED/CLOSED/CANCELLED and FINANCED — which also covers DELIVERED/SET_COMPLETE). Dual `deal_status`/`payment_status` dimensions evolve independently on the order row.
- **Calculations** (`calc.py`): per-line tier discount summed after per-line round-half-up (pinned mode b); doc fee on (subtotal − discount) clamped [25000, 75000] (pinned mode c); annuity via Decimal power (`verified`: 118750 @700bps/120mo → 1379, @720bps → 1391); escort thresholds ≥14.0/≥16.0; transport quote 5-term exact sum incl. Saturday/Sunday flat; trade-in provisional (year − declared − 10 grace, 3%/yr, 200k floor) vs final (appraised − recon, floored); warranty windows (delivered+365d / set+90d, inclusive end; TRANSPORT_DAMAGE state-gated, null window); delay comp (0 <3 days, else min(75000, (days−2)·7500)); half-open crew windows with per-date section loads; lot fit with equality allowed.
- **Cascades** (`services.py`): order cancel = unit release + lot release + SCHEDULED/DELAYED job cancellation + eval/application supersession + deposit refund, one order version bump; bubble-ups (eval approve/reject, financing approve/fund, deliver, complete-set with chained SET_COMPLETE→TITLED for chattel with ISSUED title, title issue/convert); 3-deep trade-in accept cascade (unit creation → order credit → DRAFT/SUBMITTED application recompute).
- **OCC**: `expected_sales_order_version` on evaluation/financing creation only → 412 `ERR_STALE_VERSION`, checked after existence, before state preconditions.
- **Validation pipeline**: every handler runs checks in the PRD §2.8 priority order (auth → role → ownership → path FKs → body FKs → OCC → state → business rules 9–32 → field shape last); two ordering bugs found and fixed during verification (warranty coverage 25 was after field-shape; `ERR_UNIT_ORDER_MISMATCH` was missing from the catalog).

## Boot-verification evidence

- `bash start.sh` on PORT 19877 (evaluator-style): clock set → 200, model create → 201, missing headers → 401. Boot < 3s.
- Two smoke suites (~150 calls each) run against fresh boots on port 19871, all passing: full pipeline (model→lot reserve→order→options/void→confirm w/ deposit gate→eval OCC 412→findings ownership 403→approve bubble→financing floor 422→title gate 409→fund→escort 422→quote assertion (252,000 for 2 sections/150mi/1 escort)→crew booked_dates→delay 5-day comp 22,500→dispatch window 409→deliver→set→chained TITLED→close→warranty segregation 403→expired claim 422) and suite B (lead-time 409→mark-ready, TRADE_IN direct-create 400, placement/financing 422s, lot-fit equality, unit-held 409, reject→DRAFT loop, evaluator-cap 409, trade-in provisional=1,476,000 assertion, accept cascade + counter-offer supersession, reconditioning pipeline, title surrender, full cancel cascade with REFUNDED, crew-capacity 409 with half-open adjacency allowed, multiwide-capability 422, unit-order-mismatch 422, CONDITIONAL→second APPROVE, rate-lock breach → EXPIRED + 409).
- Fresh-reboot emptiness confirmed (`data: []` on first GET after restart) — safe for `--isolation per-test-server`.

## Step 7: Run Tests and Iterate — 2026-08-14T16:00:00.000Z

All 8 rounds pass 106/106 with zero failures. Clean sweep achieved.

## Summary

- **Iterations run:** 2 (iteration 1: 93/106 across all 8 rounds with 13 deterministic failures; iteration 2: 106/106 × 8 rounds, zero failures).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:**
  - `test_helpers/api_errors.py` — added `ERR_UNIT_ORDER_MISMATCH = "ERR_UNIT_ORDER_MISMATCH"` to the `ApiErrorId` enum and its `422` entry in `HTTP_STATUS_CODES`. The error identifier and status are named verbatim in PRD §2.8 rule 29 ("the job's `home_unit_id` must equal the order's unit, else `ERR_UNIT_ORDER_MISMATCH` (HTTP 422)"); the helper enum simply omitted it, breaking `test_booking_unit_mismatch_rejected` and `test_unit_mismatch_surfaces_once_escort_satisfied` with `AttributeError`.
  - `test_helpers/fixtures.py` — `progress_to_delivered` reordered so `book_transport` runs after `progress_to_financing_approved` but before `issue_title_for_order`/`fund_application`. PRD §3.6 gates booking on `deal_status` exactly `FINANCING_APPROVED`, and §3.5 funding bubbles the order to `AWAITING_DELIVERY`, so booking must precede funding. (Dead helper — no current test_suite caller — but fixed so the shared chain is PRD-faithful.)

- **Fixes applied to `test_suite/`:**
  - `test_09_warranty.py` — `_installed_scenario` reordered from `progress_to_funded → book_transport` to `progress_to_financing_approved → book_transport → issue_title_for_order → fund_application` (same PRD §3.6/§3.5 ordering constraint); imports updated accordingly. This unblocked all 9 warranty tests that failed at the `book_transport` setup step with `ERR_INVALID_STATE`.
  - `test_08_delivery_delay.py` — `test_complete_set_permit_missing_rejected` inline chain reordered so `book_transport` precedes `issue_title_for_order`/`fund_application` (same PRD ordering constraint).

- **Fixes applied to `implementation/`:**
  - `workspace/implementation/routes/orders.py` — `confirm_order` state gate relaxed from requiring both `deal_status == "DRAFT"` AND `payment_status == "UNPAID"` to requiring only `deal_status == "DRAFT"`. PRD §3.4 names the confirm gate as a `DRAFT` order ("A `SalesConsultant` confirms a `DRAFT` order by supplying `deposit_cents`") and explicitly describes the rejection loop as returning the order to `DRAFT` so the desk can "re-spec the deal and evaluate again" — after which payment is still `DEPOSIT_PAID`. The extra `UNPAID` conjunct made the PRD-described re-confirmation path unreachable; `test_eval_reject_returns_order_to_draft` exercises exactly that loop.

## Step 8: Finalize PRD — 2026-08-14T16:20:00.000Z

Both edits are in place and the diff is exactly the two intended changes. Final verification of my pre-edit obligations is complete. Here is the summary.

## Result

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1745_manufactured_modular_home_dealer/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md = 373 lines; PRD_FINALIZED.md = 374 lines; delta = +1 line (+0.27%). Two edits total: one in-place paragraph extension in §3.4, one added table row in §5.

## Changes (one bullet per change)

- **§3.4** — *revise* — Extended the confirmation paragraph with: the confirmation gate inspects `deal_status` only (any `DRAFT` order may be confirmed whatever its `payment_status`); an order returned to `DRAFT` by the evaluation-rejection loop still carries `payment_status` `DEPOSIT_PAID` and can be confirmed again, with the newly supplied `deposit_cents` replacing the previously recorded deposit — `implementation/routes/orders.py:191` (gate is `deal_status != "DRAFT"` only), `implementation/routes/orders.py:201-205` (deposit overwritten, payment set `DEPOSIT_PAID`, amount financed recomputed, version bumped), `implementation/services.py:136-139` (reject bubble drops to `DRAFT` without touching payment).
- **§5** — *insert* — Added the missing catalogue row `| ERR_UNIT_ORDER_MISMATCH | 422 |` between `ERR_DELAY_NOTIFICATION_REQUIRED` and `ERR_DEPOSIT_INSUFFICIENT` — `implementation/errors.py:38` (`"ERR_UNIT_ORDER_MISMATCH": 422`), `implementation/routes/transport.py:109` (sole raise site).

## Step-7 items with no PRD edit (and why)

- `test_helpers/fixtures.py` reorder, `test_09_warranty.py` reorder, `test_08_delivery_delay.py` reorder — all three trace to one constraint the PRD already pins verbatim: §3.6 ("an order whose `deal_status` is exactly `FINANCING_APPROVED` — booking in any other deal state fails with `ERR_INVALID_STATE`", matched by `transport.py:83-84`) plus §3.5 (funding "bubbles the order `FINANCING_APPROVED` → `AWAITING_DELIVERY`", matched by `services.py:149-154`). Book-before-fund was already uniquely determined; these were pure fixture bugs.

## Per-edit pre-edit search log

**Edit 1 (§3.4 confirmation gate):**
- (a) Subject: confirm endpoint's state precondition and re-confirmation deposit handling.
- (b) Paths enumerated and read/grepped: `implementation/routes/orders.py:184-206` (confirm_order — the only confirm endpoint; gate, deposit overwrite, payment set, amount-financed recompute, version bump); `orders.py:103-104` (order born `DRAFT`/`UNPAID`); `orders.py:137,173` (option add/void `DRAFT` gates — separate subjects); `implementation/services.py:123-139` (approve/reject bubbles — reject leaves payment untouched); `services.py:149-154` (funding bubble sets `FINANCED`, unreachable from `DRAFT`); `services.py:220-221` (cancel refunds when `DEPOSIT_PAID` and deposit > 0); global greps for `UNPAID` and `DEPOSIT_PAID` confirming no other path inspects `payment_status` as a confirm precondition. Reachable `payment_status` values at `DRAFT` verified to be only `UNPAID` (fresh) and `DEPOSIT_PAID` (post-rejection); `REFUNDED`/`FINANCED` pairings with `DRAFT` are unreachable.
- (c) Wording adjustment: scoped the sentence strictly to the confirmation gate ("The confirmation gate inspects `deal_status` only") so it says nothing about the option add/void `DRAFT` gates or the cancel refund; kept the existing "moves `payment_status` from `UNPAID` to `DEPOSIT_PAID`" verbatim (still true on first confirmation, and §2.9 repeats it) and described re-confirmation only as replacing the recorded deposit — matching the idempotent `DEPOSIT_PAID` re-set at `orders.py:203`.

**Edit 2 (§5 catalogue row):**
- (a) Subject: `ERR_UNIT_ORDER_MISMATCH` identifier → HTTP status mapping.
- (b) Paths enumerated and read/grepped: `implementation/errors.py:38` (status map, sole status assignment); `implementation/routes/transport.py:107-109` (sole raise site); repo-wide grep for `ERR_UNIT_ORDER_MISMATCH` confirming no other occurrence; cross-checked PRD §2.8 rule 29 and §3.6, which already name the identifier verbatim at HTTP 422.
- (c) Wording adjustment: none — the row is verbatim-consistent with the status map and with rule 29; placement immediately before `ERR_DEPOSIT_INSUFFICIENT` preserves rule-order adjacency (rule 29 before rule 30) without disturbing other rows.

## Step 9: Complete PRD — 2026-08-14T16:45:00.000Z

The diff is exactly 15 lines changed in-place (no new sections or paragraphs). PRD_COMPLETED.md is complete. Final summary:

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_1745_manufactured_modular_home_dealer/workspace/PRD_COMPLETED.md`

**Size**: PRD_FINALIZED.md 374 lines / 62,911 chars → PRD_COMPLETED.md 374 lines / 65,508 chars (char-delta **+2,597**; all edits are inline inserts/revisions within existing paragraphs).

**Counts**: 17 ambiguity-pins, 2 mismatch-revisions.

**Changes** (one bullet each):

- §2.2 — insert — ambiguity — `api_request_timestamp` pinned to the host wall clock (logical clock governs entities/rules, not the receipt timestamp) — implementation/response.py:33
- §2.3 — insert — ambiguity — list ties on identical `created_at` broken by creation order, earliest first — implementation/routes/catalog.py:20 (same `(created_at, _seq)` sort in orders.py:23, evaluations.py:23, financing.py:27, transport.py:26, titles.py:21, warranty.py:24, tradein.py:24)
- §2.3 — insert — ambiguity — `has_more` pinned to `offset + returned_items < total_count` — implementation/response.py:47
- §2.5 — insert — ambiguity — entity `created_at`/`updated_at` stamped from the logical clock, never wall clock — implementation/db.py:45-56, clock.py:9
- §2.8 layer 3 — insert — ambiguity — ownership evaluated only once the anchoring resource exists; missing claim/appraisal/evaluation/referenced order yields the not-found error first — implementation/routes/warranty.py:40-51,161-163; tradein.py:152-154; evaluations.py:97-101
- §2.8 layer 33 — revise — ambiguity — numeric ranges enumerated: all cents fields, `apr_bps`, `distance_miles`, `escort_vehicle_count`, `factory_lead_time_days` non-negative integers; `section_count`/`quantity`/`crew_size`/`max_sections`/`max_sections_per_window`/`term_months` ≥ 1; `width_ft`/`length_ft`/`max_length_ft` > 0 — implementation/validate.py:62-95 and per-route Shape calls
- §3.1 — revise — ambiguity — `section_count` per-floor-plan counts pinned as descriptive conventions; only a minimum of 1 enforced — implementation/routes/catalog.py:34
- §3.1 — insert — ambiguity — registering a unit against a `DISCONTINUED` model rejected with `ERR_INVALID_STATE` (409) — implementation/routes/units.py:33-34
- §3.2 — revise — ambiguity — direct `TRADE_IN` unit registration rejected with `ERR_VALIDATION` (400) — implementation/routes/units.py:41-42
- §3.2 — revise — **mismatch** — `condition_grade` recorded as supplied; no per-`unit_kind` grade constraint (PRD had asserted new stock/factory units carry `NEW`) — implementation/routes/units.py:25,45-56
- §3.4 — insert — ambiguity — confirmation also recomputes `amount_financed_cents` against the new deposit — implementation/routes/orders.py:204,209-211
- §3.4 — insert — ambiguity — evaluation scheduling carries no `deal_status` precondition (only OCC, capacity, no-past) — implementation/routes/evaluations.py:30-76
- §3.5 — insert — ambiguity — origination permitted only from `SITE_APPROVED`/`PENDING_FINANCING`, else `ERR_INVALID_STATE` — implementation/routes/financing.py:49-51
- §3.5 — insert — ambiguity — `down_payment_cents` below the recorded deposit rejected with `ERR_VALIDATION` (400) — implementation/routes/financing.py:61-62
- §3.5 — insert — ambiguity — second decide may omit `apr_bps` (the `CONDITIONAL`-recorded rate stands); a freshly supplied `apr_bps` still floor-checked — implementation/routes/financing.py:155-164,172-173
- §3.6 — insert — ambiguity — `DelayNotice` records the declared `buyer_notified` flag — implementation/services.py:267-283
- §3.6 — insert — ambiguity — order-level notice with `new_date` not after `original_date` rejected with `ERR_VALIDATION` — implementation/routes/transport.py:334-336
- §3.8 — revise — **mismatch** — install-anchored (`INSTALLATION_DAMAGE`) claims require the unit `INSTALLED` (not `ON_SITE`-or-`INSTALLED` as PRD stated); `FACTORY_DEFECT` keeps `ON_SITE`/`INSTALLED`; any state-gate breach rejected with `ERR_WARRANTY_EXPIRED` (422) — implementation/routes/warranty.py:58-76
- §3.9 — insert — ambiguity — `supersedes_appraisal_id` cross-order reference → `ERR_VALIDATION` (400); non-`OFFERED` reference → `ERR_INVALID_STATE` (409) — implementation/routes/tradein.py:45-52

Everything else in the walk (all 60+ endpoints, both order state dimensions, cancellation cascade, bubble-ups, OCC guard, escort/quote/annuity/pricing/trade-in formulas, rate lock, warranty windows, segregation of duties, RBAC table, error catalogue) was already uniquely pinned by PRD_FINALIZED.md and matches the implementation; no changes needed there.
