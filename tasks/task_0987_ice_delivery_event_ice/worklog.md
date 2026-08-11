# Worklog — task_0987_ice_delivery_event_ice

Scenario: generate task hard than expert level! 987. Ice-Delivery & Event-Ice Service: order (block/cube/dry-ice) & volume, event & recurring (bar/restaurant) route, delivery window & cold storage, dry-ice safety/handling, pallet/bag & pricing, will-call, billing, seasonal surge

## Step 1: Create Task Directory — 2026-08-10T10:44:50.265Z

Task directory `tasks/task_0987_ice_delivery_event_ice/` and its `workspace/` subdirectory were pre-assigned and already exist on disk. Step 1 auto-index scan skipped per headless run instructions; treated as done.

## Step 2: Generate Scaffold — 2026-08-10T11:20:37.487Z

Scaffold generation complete. All three artifacts exist on disk and pass `scaffold_lint.py` with **VERDICT: clean lint** (654 §1.8/§1.9 calls scanned, 0 violations; all FK reverse-reachability checks pass).

**Files:**
- `/home/ubuntu/github/CodingPRD/tasks/task_0987_ice_delivery_event_ice/SCAFFOLD.yaml` (§1.0–§1.7; no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_0987_ice_delivery_event_ice/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_0987_ice_delivery_event_ice/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Summary counts:**
- Entities: **14** (Depot, Customer, HandlerCertification, PriceBook, SurgeWindow, RecurringRoute, Order, OrderLine, DeliverySlot, ColdStorageHold, DispatchRun, Invoice, Payment, WaitlistEntry)
- State machines: **9** — Order (parallel fulfillment_status × billing_status dimensions with a CONFIRMED→WAITLISTED→CONFIRMED fork/cycle), RecurringRoute (ACTIVE⇄PAUSED cycle), DeliverySlot (OPEN⇄FULL cycle + sweep closure), ColdStorageHold, DispatchRun, Invoice (ISSUED/PARTIALLY_PAID/OVERDUE lattice + void compensation), HandlerCertification (suspend/reinstate cycle + expiry sweep), WaitlistEntry, PriceBook (SCHEDULED→ACTIVE→SUPERSEDED)
- Calculations: **11** (tiered line pricing with per-line dry-ice handling fold-in, pinned-order total composition with PROVISIONAL/FINAL variants, SETTLED vs FORWARD_LOOKING credit exposure, freezer aggregate + posture, bunker exclusive-buffer intervals, slot capacity, surge admission, waitlist selector with 4-level deterministic tie-break, payment waterfall, invoice consolidation, 8-step pinned ops-run sweeps)
- Validations: **30** (ordered: auth → authz → schema → existence → OCC → terminal → state → safety → temporal → constraint → fiscal)
- Endpoints: **59** (incl. `POST /_clock/set_current_utc` with mandatory default `2026-05-01T00:00:00Z`, and `POST /depots/{id}/run-ops` checkpoint)
- Errors: **29**
- Roles: **6** (PlatformAdmin, DepotManager, Dispatcher, BillingClerk, SafetyOfficer opaque; CustomerAgent entity_backed:Customer; segregation-of-duties on invoice issue/void)
- Concurrency rules: **2** true OCC races (order reprice, route standing-order patch)
- §1.8 instances: **19** — all 9 rules × ≥2; combinatorial_formula carries 3 (one per mode a/b/c). All formula-derived asserts are pre-computed literals verified by script (e.g., provisional 51450 vs final 58718; per-line rounding 23113 vs sum-then-round 23112; depth-4 cancel→release→posture→promote→confirm cascade ending at posture SURGE_CONSTRAINED with free == 1)
- §1.9 instances: **55** (51 active + 4 `excluded_because` stubs), spanning all nine claim-guide sections: entities 6, state_machines 18, calculations 6, validations 9, endpoints 3, errors 7, rbac 2, cross-cutting layers 3, consistency 1

**Design highlights (beyond-expert difficulty drivers):** flat topology with 19 FKs all reverse-reachable; posture-driven gating (FROZEN blocks reserve-slot and promotion); two genuinely different interval algebras (bunker exclusive + 90-min buffer half-open adjacency vs general-freezer peak-overlap aggregate); waitlist promotion selector with tier/queued_at/event_date/created_at tie-break chain; dual-variant pricing driven by logical-clock evolution between quote and confirm; forward-looking vs settled credit exposure producing different admit/reject decisions at the same data; two compensating invariants over different conserved quantities (pallet spaces, cents); ops-run checkpoint with 8 pinned-order sweeps where sweep ordering is load-bearing (waitlist expiry before promotion).

## Step 3: Copy Shared Files — 2026-08-10T11:20:55.566Z

Copied `./INSTRUCTION.md` to `tasks/task_0987_ice_delivery_event_ice/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-10T11:34:50.932Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_0987_ice_delivery_event_ice/workspace/PRD.md` exists on disk — 342 lines, 62 KB. (The "role mismatches" line above is a substring artifact of the first checker; the row-wise recheck confirmed all 59 rows match method, path, and full role set with zero mismatches.)

## Section list

- **§1 Introduction** (2 paragraphs: business context + derived-state/logical-clock framing)
- **§2 Global Specifications & System-Wide Principles** — 2.1 RBAC (headers, all 6 roles, opaque vs entity-backed identity prose per role), 2.2 API Response Structure (emitted verbatim from `section-2.2-response-structure.md`), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 The Platform Logical Clock (startup default 2026-05-01T00:00:00Z, `to_iso8601`), 2.5 Common Resource Properties (incl. Payment/WaitlistEntry carrying only `id`+`created_at`), 2.6 Request Validation and Evaluation Order (8-rung pinned ladder, void state-rule split), 2.7 OCC (both rules), 2.8 Monetary Precision (integer cents, round half-up, per-line-before-summation), 2.9 Depot Posture & Freezer Accounting, 2.10 Nested Paths & Referential Integrity
- **§3 Business Logic & Workflows** — 3.1 Network onboarding (depots/customers/price books/surge windows), 3.2 Handler certifications, 3.3 Recurring routes & standing orders, 3.4 Composing/quoting/repricing (line pricing, pinned 7-step total composition, PROVISIONAL vs FINAL), 3.5 Slot reservation & confirmation (pinned confirm gauntlet, bunker/freezer/surge rules, WAITLISTED fork), 3.6 Holds, 4-hop cancel cascade, waitlist promotion, 3.7 Dispatch runs & will-call (3-hop start cascade, no-show), 3.8 Invoicing/payments/credit (SETTLED vs FORWARD_LOOKING, waterfall, void segregation), 3.9 Ops-run checkpoint (8 pinned sweeps, per-step id lists)
- **§4 Endpoint Definitions** — 4-column table, all 59 scaffold endpoints with exact roles
- **§5 Error Code Catalogue** — 2-column table, all 29 errors

## Hard contract reports

```
Field coverage check:
- entities[].fields + endpoint inputs + query/path params: 117 required, 117 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validation priority orderings: global 8-rung ladder in §2.6 plus per-endpoint pinned orders
  (reserve-slot, confirm, assign, invoice generate, void) all expressed — 0 missing
- concurrency_rules OCC: 2/2 expressed (reprice + standing-order patch; occ field, error id, 412 each named)
- state machine transitions: all 9 machines rendered, incl. Order's parallel fulfillment/billing dimensions,
  cancel 4-hop cascade, run-start 3-hop cascade, void hops — 0 missing
- calculations: 11/11 in precise prose (formulas reconstructible, constants embedded, no pseudocode/fuzzy words)
- validations: 30/30 matchable to error_id in §2/§3 prose
- endpoints side_effects / applies_to scopes: all expressed (incl. validation-5's 8-endpoint FK list)
- structured field content & sibling-branch symmetry: verified (cancel/void/overdue sibling branches equal density)
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 655
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional verification: all 29 error IDs appear in §2/§3 prose and §5; all enum/state values present verbatim; §2.2 block byte-identical to the canonical source; no pseudocode operators (`>=`, `==`, `+=`, …) or fuzzy approximators in the prose. The two forbidden index files were never opened, and no other `task_*` directory was accessed.

## Step 5: Generate Unit Tests — 2026-08-10T12:01:12.445Z

Both output directories are verified on disk. Final report:

## Generation complete — task_0987_ice_delivery_event_ice

**Output trees**
- `/home/ubuntu/github/CodingPRD/tasks/task_0987_ice_delivery_event_ice/test_helpers/` — 9 files: `__init__.py` (barrel), `types.py` (26 enums + 15 TypedDicts; Payment/WaitlistEntry correctly omit `updated_at`/`version`), `constants.py`, `factories.py` (5 price-book variants + all entity payloads), `api_client.py` (63 endpoint methods covering every PRD §4 row), `api_errors.py` (29 IDs, HTTP map registered via `set_error_http_status_map`), `assertions.py`, `test_users.py` (opaque-role constants + `make_customer_agent_headers`/`make_billing_clerk_headers` builders for the entity-backed/segregated roles), `fixtures.py` (composable lifecycle helpers: quote→confirm→stage→ready→pickup, delivery path with slot reservation, invoice generate/issue, overdue-invoice setup).
- `/home/ubuntu/github/CodingPRD/tasks/task_0987_ice_delivery_event_ice/test_suite/` — `conftest.py` + 12 test files.

**Per-file test counts (87 total)**

| File | Tests | | File | Tests |
|---|---|---|---|---|
| test_01_envelope_auth_rbac | 8 | | test_07_freezer_and_bunker | 6 |
| test_02_customers_and_wallets | 6 | | test_08_surge_and_waitlist | 5 |
| test_03_order_pricing | 9 | | test_09_certifications | 6 |
| test_04_credit_and_standing | 8 | | test_10_dispatch_runs | 5 |
| test_05_order_lifecycle | 13 | | test_11_invoicing_and_payments | 10 |
| test_06_slots_and_posture | 6 | | test_12_routes_and_occ | 5 |

**Queue A (difficulty): 18/19 instances translated, 36 tests (≥2 each)**
- **Skipped (1):** `combinatorial_formula/per_line_rounding_order_beats_sum_then_round`. Its asserted literals are unreachable: merch 23113 = 18779 + 4334 requires a line of round(3×1350×1.07)=4334, but 3 DRY_ICE bags price at the tier 1-9 rate 1500 under the pinned fixture book (4334 would require 3 units at the 10-49 tier price). The instance's expected values contradict the PRD's flat-tier rule, so no PRD-faithful implementation could pass it — fails unique derivability. Gap stays a gap.

**Queue B (corner): 51/51 non-stub instances translated, 51 tests.** The 4 `excluded_because:` stubs (`invoice_overdue_sweep`, `depot_posture_computed_read`, `error_hold_interval_conflict_trigger`, `immediate_consistency_confirm_response`) were not translated; all four cross-references resolve to real queue-A instances.

**Two data-fidelity repairs made during translation** (asserted literals kept verbatim; setup adjusted so a correct implementation reaches them):
1. `credit_exposure_settled_vs_forward_looking`: recipe's order2 payload (30 CUBE bags + 1 BLOCK pallet = 31500) contradicts its own asserts (candidate total 9900 = 61350−51450). Translated with 33 CUBE bags (=9900) so the B-customer equality admission (61350 ≤ 61350) actually holds.
2. `promotion_tiebreak_created_at`: as written, all four rank keys tie under a logical-clock-created_at reading (both confirms at the same fixed clock). Inserted a clock advance between B's and C's queueing so "B promoted, C stays" is uniquely derivable under every PRD reading.

**Self-check verdicts**
- Stage 1: all helper modules import cleanly; framework signatures verified against the installed `prd_bench_local_runner.testing` package; identity threading via `make_customer_agent_headers(customer_id)` throughout fixtures and tests.
- Stage 2: 87/87 tests collected by pytest; every test carries exactly one `Design:` tag; zero bogus/dual/untagged tags; queue A ≥2 and queue B ≥1 coverage machine-verified against the yamls; all 138 PRD citations survive verbatim whitespace-normalized grep of PRD.md; every asserted `error_id` appears in PRD §2/§3 prose (not just the §5 table); no `skip`/`skipif`/`xfail` markers anywhere; no scaffold references in generated code comments.

## Step 6: Generate Implementation — 2026-08-10T12:01:12.445Z

Implementation complete and verified. Both end-to-end smoke suites (happy-path lifecycle + deep-cascade/edge-case suite) pass, and the server boots cleanly via `bash start.sh` from a fresh process with an empty store.

## Summary

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_0987_ice_delivery_event_ice/workspace/implementation/`):
- `start.sh` — executable; guarded `pip install` (no-op when Flask present); `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — entry point, imports route modules, `app.run(host="0.0.0.0", port=$PORT)`
- `server.py` — Flask app, envelope error handlers (ApiError/404/405/500), record factory
- `core.py` — logical clock (default 2026-05-01T00:00:00Z, never wall-clock), envelope (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`), pagination (`limit/offset/total_count/has_more`, defaults 10/0, range 1–100, out-of-range → 400), parsing, schema validation (unknown-field rejection, non-empty lines, window/period ordering), auth (`X-User-ID`/`X-User-Role`, 6 roles, CustomerAgent entity-backed ownership)
- `store.py` — 12 in-memory dicts, starts empty, zero seeding
- `domain.py` — all calculations, derived state, cascades, promotion sweep, ops-run sweeps
- `views.py` — serializers (Payment/WaitlistEntry correctly omit `version`/`updated_at`)
- `routes_core.py` (14 routes), `routes_orders.py` (22), `routes_ops.py` (23)

**Endpoints: 59/59** from the §1.5 table. **State machines: 9** (Order with parallel fulfillment×billing dimensions, RecurringRoute, DeliverySlot, ColdStorageHold, DispatchRun, Invoice, HandlerCertification, WaitlistEntry, PriceBook). **Calculations: 11** (order_line_pricing, order_total_composition PROVISIONAL/FINAL, credit_exposure SETTLED/FORWARD_LOOKING, freezer_capacity_and_posture, bunker_interval_exclusion, slot_reservation_capacity, surge_admission, waitlist_promotion_selection, payment_waterfall, invoice_consolidation, ops_run_sweeps with the 8 pinned steps). OCC on `expected_order_version`/`expected_route_version` (412), Decimal ROUND_HALF_UP per-line then discount/surcharge only, deposit exempt from both bases, half-open interval arithmetic, validation ladder with exact scaffold error IDs/statuses, segregation of duties before not-voidable on void.

**Verified live**: tiered pricing math, dry-ice 700bps handling, quote/reprice/confirm, slot FULL-at-equality/reopen, bunker adjacency admitted vs overlap rejected, freezer peak-overlap, FROZEN gating, RATIONED waitlist fork (pricing stays PROVISIONAL, no hold), 4-hop cancel→release→posture-easing→promotion cascade, no-show/expiry/overdue/slot-closure/book-activation/route-generation sweeps, payment waterfall with OVERDUE partial-stays-OVERDUE rule, void unapplying payments to credit, period-conflict-before-empty ordering.

Two bugs found and fixed during verification: (1) the waitlist fork initially committed FINAL pricing — PRD requires PROVISIONAL until promotion; (2) release-triggered promotion sweeps ran before the transitioning order's new state was applied, so a cancelled order still counted in the surge-committed set — fixed by applying the terminal state before `release_hold` in cancel, confirm-pickup, and the no-show sweep.

**Ambiguities and interpretations chosen**:
1. **CustomerAgent read scoping** — PRD §2.1 "scoped to their own resources wherever ownership applies": implemented as 403 on detail reads of other customers' orders/routes/invoices/customer records, and list-filtering for `/orders`, `/dispatch-runs/{id}/orders`, `/depots/{id}/waitlist-entries`; infrastructure resources (depots, slots, holds, runs, books, windows) unfiltered.
2. **CLOSED slot on reserve-slot** — scaffold priority-7 lists "CLOSED slot" as terminal (ERR_ALREADY_TERMINAL), but PRD §3.5 says `ERR_INVALID_STATE`; PRD wins → `ERR_INVALID_STATE`.
3. **Depot `freezer_reserved_pallets`** — scaffold field omits zone, PRD §2.9 says bunker holds are "excluded from every freezer sum"; PRD wins → bunker holds never counted.
4. **SurgeWindow status** — derived on read from logical date (no sweep touches windows); PriceBook status stored (mutated only by create-activation/run-ops sweep).
5. **Ladder ties** — ownership (rung 2) is undecidable for nonexistent path ids, so 404 wins there; for body-carried `customer_id` on creates, ownership 403 precedes full schema validation.
6. **`GET /orders?status=`** — filters `fulfillment_status` (the primary lifecycle; billing_status left unfiltered).
7. **Book line/tier mismatch at quote** — unspecified; returns ERR_INVALID_REQUEST 400. Overlapping tiers resolve to the greatest `tier_min_units` match.
8. **Multiple covering RATIONED windows** — must fit within every cap; any covering CLOSED rejects.
9. **`daily_pallet_cap` on non-RATIONED windows** — accepted and stored if supplied (spec only mandates presence when RATIONED).
10. **Timestamps** — all stamps derive from the logical clock plus a monotonic microsecond tick, keeping created_at strictly ordered for deterministic tie-breaks while never using wall-clock.

## Step 7: Test-and-Fix Iteration — 2026-08-10

**Iteration 1 sweep:** 8/8 rounds identical — 85/87 passed; `test_success_envelope_shape` and `test_payment_immutable_ledger_row` failed deterministically on `is_valid_uuid(data.id)` (implementation minted bare-hex ids, e.g. `e614fad13c0f4427995b97c89c436134`).

**Diagnosis (both tests):** PRD §2.5 verbatim: "`id` (string): a unique server-generated identifier formatted as a UUID, with no type prefix." Coverage + unique derivability hold (canonical UUID string form is the dashed RFC 4122 layout); tests faithful. Implementation bug.

**Fix:** `workspace/implementation/core.py` `new_id()`: `uuid.uuid4().hex` → `str(uuid.uuid4())`.

**Iteration 2 sweep:** 8/8 rounds 87/87 passed. No test deletions, no test_helpers changes.

## Step 7: Test-and-Fix Iteration (orchestrator record) — 2026-08-10T12:10:47.962Z

**Summary (verbatim from fix subagent)**

- **Iterations run: 2** (sweep 1: 85/87 in all 8 rounds, same 2 failures each; fix applied; sweep 2: **87/87 in all 8 rounds — clean exit**).

- **Tests deleted: none.** Both failing tests traced to a verbatim PRD sentence with unique derivability.

- **Fixes applied to `test_helpers/`: none.** The tests and the runner's `is_valid_uuid` helper faithfully express the PRD rule.

- **Fixes applied to `implementation/`: one.**
  - `/home/ubuntu/github/CodingPRD/tasks/task_0987_ice_delivery_event_ice/workspace/implementation/core.py`, `new_id()`: changed `uuid.uuid4().hex` → `str(uuid.uuid4())`. PRD §2.5 requires "`id` (string): a unique server-generated identifier formatted as a UUID" — the canonical dashed RFC 4122 form. The implementation was minting 32-char bare-hex ids, which broke `test_success_envelope_shape` (test_01) and `test_payment_immutable_ledger_row` (test_02) deterministically in every round. Verified nothing else in the implementation depends on the bare-hex shape (ids are opaque strings; no parsing/length checks).

**Failure analysis detail:** Both failures were deterministic (identical in 8/8 rounds), not flaky — a single global root cause in id minting. After the one-line fix, the full 8-round parallel sweep passed 87/87 in every round with zero failures and zero flakiness.

## Step 8: Finalize PRD — 2026-08-10T12:12:51.608Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_0987_ice_delivery_event_ice/workspace/PRD_FINALIZED.md` produced.

## Summary

**Line counts**: PRD.md 342 lines; PRD_FINALIZED.md 342 lines; 0% delta (one line revised in place, same count).

**Changes (1 edit)**:
- **§2.5 Common Resource Properties** — revise — line 82 bullet `id`: pinned the previously open UUID string representation to the canonical dashed RFC 4122 form (five hyphen-separated hex groups 8-4-4-4-12, 36 chars, lowercase) — `workspace/implementation/core.py:62-63` (`new_id()` returns `str(uuid.uuid4())`).

**Why the edit was needed**: the step_7 diff item (uuid4().hex → str(uuid4())) was not a pure implementation bug. PRD §2.5's "formatted as a UUID" admits the bare-hex reading — the original implementation itself read it that way, and Python documents `.hex` as "the UUID as a 32-character hexadecimal string." A fresh implementer could legitimately mint 32-char bare-hex ids, so the wording did not uniquely determine the behavior. The revision removes that ambiguity while changing nothing else.

**Per-edit pre-edit search log**:
- (a) Subject: string format of the server-generated `id` field on all resources, including the slimmer Payment/WaitlistEntry records (§2.5 line 87) whose ids come from the same mint.
- (b) Impl paths enumerated and verified: `core.py:62-63` (sole minting site, `str(uuid.uuid4())`); all six call sites — `server.py:39` (resource factory), `routes_ops.py:478` (Payment), `domain.py:271` (hold), `domain.py:450` (WaitlistEntry), `domain.py:534` (Order), `domain.py:550` (OrderLine); `core.py:86` (`api_request_id`, separate `req_`-prefixed generator, pinned separately by §2 line 42 — deliberately untouched); grepped for any id parsing/validation/length checks (none — ids are opaque on every read/lookup path); grepped PRD.md for all other id-format statements (only lines 42 and 60, both unrelated templates). Auxiliary evidence: test helper `is_valid_uuid` regex in `prd_bench_local_runner/testing/assertions.py:19-21` requires the dashed 8-4-4-4-12 form.
- (c) Wording adjustment: scoped the revision to the entity-`id` bullet only; included "lowercase" (true of every minted id across all enumerated paths) and kept "with no type prefix" verbatim so `api_request_id` and error-envelope identifiers remain undisturbed. No path enumerated would be mis-described by the new sentence.

## Step 9: Complete PRD — 2026-08-10T12:22:05.866Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_0987_ice_delivery_event_ice/workspace/PRD_COMPLETED.md` produced.

**Size:** PRD_FINALIZED.md 342 lines / 62,441 chars → PRD_COMPLETED.md 342 lines / 65,840 chars (char-delta **+3,399**, line-delta **0** — all edits are in-paragraph inserts/revisions; no new sections).

**Counts:** 13 ambiguity-pins, 5 mismatch-revisions (18 edits across 16 paragraphs).

**Changes** (`{section} — {insert|revise} — {ambiguity|mismatch} — {what} — {impl ref}`):

- §2.3 — insert — ambiguity — out-of-range/non-integer `limit`/`offset` rejected `ERR_INVALID_REQUEST` (400) — core.py:242-264
- §2.4 — insert — ambiguity — clock-set echoes new value as `current_utc`; every stamp is logical clock plus strictly increasing microsecond offset (monotonic tick), so `created_at` ordering coincides with creation order — routes_core.py:17-25; core.py:16-59
- §2.6 rung 2 — insert — ambiguity — for path-addressed owned resources, existence (404) is confirmed before the ownership comparison (403), since ownership requires the loaded resource — routes_orders.py:241-243 (pattern throughout)
- §2.6 rung 3 — revise — mismatch — qualified "the `lines` array is non-empty" to order `lines` and route `standing_lines` only (price-book `lines` may be empty); also pinned: numeric field minima enforced as `ERR_INVALID_REQUEST` except the two business-coded minima, `tier_max_units >= tier_min_units`, surge `start_date <= end_date`, and bodyless endpoints imposing no schema checks — routes_core.py:169-191, 269-270; core.py:190-236
- §2.6 rung 7 — revise — mismatch — removed `a CLOSED slot` from the `ERR_ALREADY_TERMINAL` list; reserving against a CLOSED slot fails with `ERR_INVALID_STATE` per §3.5's gauntlet — routes_orders.py:445-446
- §3.1 (surge windows) — insert — ambiguity — `daily_pallet_cap` on `OPEN`/`CLOSED` windows: optional, but when supplied it is validated (integer ≥ 1), stored, echoed, and never consulted outside `RATIONED` admission — routes_core.py:273-284
- §3.2 — revise — mismatch — dropped the claim that `certificate_number` is unique within a customer's certifications; no uniqueness is enforced — routes_core.py:103-120
- §3.4 (creation) — insert — ambiguity — at creation the lead-time check fires before line-quantity validation — routes_orders.py:210-214
- §3.4 (line pricing) — insert — ambiguity — overlapping satisfied tiers resolve by greatest `tier_min_units`; a line matching no tier fails with `ERR_INVALID_REQUEST` (400) — domain.py:158-170
- §3.4 (filters) — insert — ambiguity — the `status` collection filter matches only `fulfillment_status` — routes_orders.py:260-262
- §3.5 (confirm gates) — revise — ambiguity — the capacity gate is exclusive: bunker exclusion for dry-ice orders XOR freezer peak-overlap for non-dry-ice orders, never both — routes_orders.py:344-353
- §3.5 (surge admission) — insert — ambiguity — multiple covering windows: any `CLOSED` rejects; every covering `RATIONED` window must individually admit, a single failure forks to `WAITLISTED` — routes_orders.py:355-365
- §3.6 (cancel) — insert — ambiguity — the order lands on `CANCELLED` before any release hop, so its pallets leave slot and surge-committed totals before the promotion sweep — routes_orders.py:404-410
- §3.7 (assign) — insert — mismatch — run terminal/required-state guards fire before `order_ids` body references are resolved (non-`PLANNED` run yields its state error even for nonexistent order ids), an acknowledged exception to the rung-5-before-7/8 ladder — routes_ops.py:157-163
- §3.7 (pickup) — insert — ambiguity — the pickup window is checked against the order's active hold, or its most recent hold when none is active — routes_orders.py:510
- §3.8 (credit exposure) — revise — mismatch — the pipeline sums each order's currently stored `total_cents` (`FINAL` once confirmed, still `PROVISIONAL` while `WAITLISTED`), not a universal `FINAL` figure — domain.py:369-374; routes_orders.py:380-383
- §3.9 — insert — ambiguity — depot scoping: slot-closure, no-show, waitlist-expiry, route-generation, and promotion sweeps act only on this depot's records; book activation, certification expiry, and invoice aging are platform-global — domain.py:589-668
- §3.9 — insert — ambiguity — multiple due books activate in ascending `effective_from` (ties by creation order), each superseding the last; each returned identifier list follows its sweep's iteration order (creation order, except `activated_book_ids` and `promoted_entry_ids`) — domain.py:590-600, 581-585

**Hint-list dispositions where no change was made:** CustomerAgent read scoping (§2.1's "any resource that references a customer" plus the waitlist-via-order rule already uniquely determines impl's scoped/unscoped split, including unscoped depot-level lists of holds/slots/windows/runs); bunker holds excluded from freezer sums (already pinned in §2.9); derived-vs-stored status fields (slot `FULL`/`OPEN`, window status, posture, and standing are all already pinned as derived; book status as stored).
