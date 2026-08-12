# Worklog — task_0988_propane_cylinder_exchange_refill

Scenario: Propane Cylinder Exchange & Refill: cage inventory & exchange, refill vs swap & pricing, cylinder certification/recert & condemn, DOT/handling compliance, restock route & par, host-site commission, safety/leak, reconciliation

Difficulty parameter: "generate task hard than expert level!"

## Step 1: Create Task Directory — 2026-08-10T00:00:00.000Z

Task directory and workspace/ pre-assigned by the headless run command (auto-index scan skipped per instructions): `tasks/task_0988_propane_cylinder_exchange_refill` with `workspace/` subdirectory. Verified both exist on disk.

## Step 2: Generate Scaffold — 2026-08-10T11:36:00.000Z

All three scaffold artifacts are written to `/home/ubuntu/github/CodingPRD/tasks/task_0988_propane_cylinder_exchange_refill/` and pass `scaffold_lint.py` with **VERDICT: clean lint** (65 endpoints, 12 entities, 22 §1.8 instances, 55 §1.9 instances, 616 calls scanned, zero violations; all FKs reverse-reachable).

**SCAFFOLD.yaml counts** (§1.0–§1.7 only, no design keys):
- **Entities: 12** — HostSite, PricingPolicy, Driver, Technician, Cylinder, ExchangeOrder, RefillTicket, CertificationRecord, LeakReport, RestockRun, CommissionStatement, ReconciliationSession (flat topology, FK cross-links)
- **State machines: 11** — including Cylinder (cyclic CERTIFIED→RECERT_DUE→CERTIFIED cert dimension parallel to FULL/EMPTY/QUARANTINED fill dimension), ReconciliationSession (recount revert loop), CommissionStatement (dispute loop), RefillTicket (reweigh loop)
- **Concurrency rules: 3** — all true create-with-supersede races resolved via OCC on HostSite.version (`restock-run-create`, `pricing-policy-create`, `site-config-patch`), HTTP 412
- **Calculations: 10** — incl. `refill_charge` (tiered marginal per-lb, per-tier rounding pinned, 80% fill rule), `commission_settlement` (marginal tier straddle, per-sale round-then-sum pinned, GROSS/NET variants, leak-penalty floor), `reconciliation_expected_cash` (BOOK/PHYSICAL baseline variants), `restock_suggested_qty` (pinned avg→forecast→project→clamp order)
- **Validations: 14 priority rows** — auth → existence → OCC → state → safety → temporal → constraint → referential → fiscal → segregation-of-duties
- **Endpoints: 65** — including `POST /_clock/set_current_utc` (default 2026-05-01T00:00:00Z stated), action endpoints, filtered lists for every FK
- **Errors: 34** — every one referenced by ≥1 validation/transition and exercised by ≥1 test instance
- **Roles: 6** — PlatformAdmin/SiteClerk/ComplianceOfficer (opaque), Driver/Technician/HostSiteManager (entity-backed); segregation_of_duties on verify-vs-driver, resolve-vs-clerk, condemn-confirm-vs-requester, leak-resolve-vs-reporter

**SCAFFOLD_DIFFICULTY_DESIGN.yaml: 22 instances** (all 9 rules ≥2): dual_variant 2 (reconciliation baseline BOOK-vs-PHYSICAL ±3000 divergence; commission GROSS 962 vs NET 271 on identical data), combinatorial 3 (modes a/b/c all covered), non-linear SM 2, cascades 2 (leak-confirm depth-3 quarantine chain; condemn-confirm depth-3 alert-flip chain), priority conflicts 3 (state/fiscal, safety/constraint, temporal/constraint), boundaries 3 (overfill 19.99 lbs equality, exactly-500-cent variance flags, expiry-day strict-greater), cross-entity 3 (three distinct entity pairs), temporal overlap 2 (half-open policy windows vs whole-day driver intervals), invariants 2 (cylinder population 11==11 across swap; expected cash 20000→22705→20000 across complete+refund). Every formula-derived assert is a literal verified by executing the formulas in Python.

**SCAFFOLD_CORNER_DESIGN.yaml: 55 instances** — 45 active (entities/state-machines/calculations/validations/endpoints/errors/RBAC/cross-cutting/consistency sections) + 10 `excluded_because` stubs all citing existing difficulty-instance names.

**Notable design decisions**: computed-on-read cage counts (no HostSite version bump from sales, keeping OCC deterministic); restock runs are single-site with draft-supersede semantics; customer cylinders registered as `owner_kind: CUSTOMER` so refill certification checks stay cross-entity; refund quarantines the issued cylinder (compensation cascade); commission tier threshold is site-configurable so tier-straddle is testable with small amounts; the logical clock drives the RECERT_DUE sweep, refund windows, commission period closure, and arrive-date checks.

## Step 3: Copy Shared Files — 2026-08-10T11:37:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_0988_propane_cylinder_exchange_refill/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T11:47:00.000Z

All three hard contracts pass mechanically. The PRD is complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_0988_propane_cylinder_exchange_refill/workspace/PRD.md` (320 lines, ~58 KB)

## Section list

- **§1 Introduction** — 2 paragraphs (counter-motion business context + compliance envelope; logical-clock determinism)
- **§2 Global Specifications** — 2.1 RBAC (6 roles, per-role `identity` prose incl. entity-backed Driver/Technician/HostSiteManager vs opaque PlatformAdmin/SiteClerk/ComplianceOfficer), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending), 2.4 Common Resource Properties & Logical Clock (UUID `id`, 3-fraction-digit timestamps, `version` semantics, startup clock `2026-05-01T00:00:00Z`, RECERT_DUE sweep), 2.5 Money/Weight/Rounding (whole cents & 2dp lbs round-half-up; per-tier/per-sale rounding before summing; basis-point doctrine), 2.6 OCC (3 guarded writes, `expected_site_version`, `ERR_STALE_VERSION` 412), 2.7 Request Evaluation Order (all 14 validation priorities in explicit numbered order), 2.8 Cage Inventory Accounting & Sales Posture, 2.9 Sale Sequencing/Idempotency
- **§3 Business Logic** — 8 subsections: 3.1 Host sites/pricing/decommission, 3.2 Cylinder registration & certification cycle, 3.3 Exchange counter, 3.4 Refill bay, 3.5 Leak response & quarantine, 3.6 Restock logistics, 3.7 Commission settlement & disputes, 3.8 Daily reconciliation
- **§4 Endpoint Definitions** — 65-row table, 4 columns (Method, Path, Description, Authorized Roles), 201/200 status rule paragraph
- **§5 Error Code Catalogue** — 34-row table, 2 columns (Error ID, HTTP Status)

## Coverage audit

- **Contract 1 (field names):** 142 required identifiers (entity fields + endpoint inputs + query params + path params + envelope fields) — 142 present in backticks, 0 missing (script-verified).
- **Contract 2 (rules):** All 14 validation priorities rendered as an explicit ordered evaluation sequence (§2.7); all 3 OCC rules named with endpoint/field/error-id in stale-version framing only (§2.6); all 10 calculations in reconstructible prose — cert expiry (12y initial, 5/7y recert, strict-greater sweep), swap charge (pinned prices, deposit zeroed on return, tax rounded once), refill charge (0.42 fill factor, 0.10 lb tare tolerance, per-tier rounding then sum, inclusive overfill ceiling), commission settlement (sale_seq-ordered marginal tier walk, per-sale rounding, GROSS vs NET, 25,000-cent leak penalty, zero floor), reconciliation cash (BOOK/PHYSICAL baselines, inclusive 500-cent flag), cage counts, 14-day half-open forecast with ceil and clamp, 37/17-lb payload check, posture/floor derivation, oldest-certified selector (site + depot reuse); every state-machine transition across all 11 machines rendered with preconditions paired to error IDs and all side-effect cascades (condemn 3-hop, leak-confirm cascade incl. SAFETY auto-voids, refund quarantine return, restock metal movements); sibling branches symmetric (confirm/reject, GROSS/NET, BOOK/PHYSICAL, BALANCED/FLAGGED, draft/dispatched cancel).
- **Contract 3 (§3 path purity):** 589 backticked tokens scanned in §3 — 0 paths, 0 bare HTTP methods, 0 method+path combos (script-verified). Endpoints referenced via state-pair framing and role+verb only.
- **Spot checks:** all 34 error IDs appear in §2/§3 narrative; all enum/state strings present verbatim; no pseudocode operators (`>=`, `==`, `min(`, etc.) in §2/§3 prose; forbidden design-index files were never opened.

## Step 5: Generate Unit Tests — 2026-08-10T12:12:00.000Z

Generation complete. All outputs verified.

## File inventory

**`/home/ubuntu/github/CodingPRD/tasks/task_0988_propane_cylinder_exchange_refill/test_helpers/`** (9 files):
- `types.py` — 12 entity TypedDicts (all `common_fields: true` → id/created_at/updated_at/version) + 16 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per each of the 63 PRD §4 endpoints
- `api_errors.py` — 34-entry `ApiErrorId` + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions + `assert_site_cage_invariants` (inclusive restock-alert invariant)
- `factories.py` — 12 payload factories with collision-free serial/license numbering
- `constants.py` — PRD thresholds (0.42 fill factor, 0.10 tare tolerance, 500-cent variance, 37/17 lbs DOT weights, 25000 leak penalty, 62-day period cap, 14-day forecast window) + standard policy P and its derived money figures (2705/6494/6282/19.99)
- `test_users.py` — shared opaque-role headers + per-instance builders for the three entity-backed roles
- `fixtures.py` — composite helpers: priced sites, cylinder registration, order/refill lifecycle walkers, reconciliation open/count/BALANCED, condemn two-signature flow, leak lifecycle, restock dispatch scenarios, statements
- `__init__.py` — barrel export

**`test_suite/`** (conftest + 9 test files, 98 tests): `test_01_sites_and_pricing` (13), `test_02_cylinders_certification` (9), `test_03_exchange_orders` (20), `test_04_refill_tickets` (11), `test_05_leaks_quarantine` (6), `test_06_restock_runs` (12), `test_07_reconciliation` (7), `test_08_commission` (9), `test_09_rbac_security` (11).

## Coverage

- **Queue A (Difficulty): 22/22 instances, 44 tests** (exactly 2 per instance)
- **Queue B (Corner): 54/55 non-stub instances, 54 tests** (1 per instance); all 10 `excluded_because:` stubs verified to resolve to real queue-A instances and not translated

## Skip list (1 instance)

- `Corner/endpoints/filtered_cylinder_list` — PRD §4 says only "List cylinders with filters"; the specific filter names (`current_site_id`, `fill_status`) never appear in PRD prose (unlike the explicit filter enumerations for orders, tickets, leaks, runs, statements, sessions). Fails the coverage condition; two PRD-only readers could ship different filter sets.

## Audits passed

- Every test has exactly one `Design:` tag resolving to a real instance (script-verified against both YAMLs).
- Every docstring contains at least one ≥8-word quote surviving literal substring match against PRD.md (0 mismatches after fixing one semicolon termination and one markdown-bold stage title).
- No `skip`/`skipif`/`xfail` markers; no scaffold/table references in generated code; pytest collects all 98 tests cleanly.

## Key design decisions

- **Identity mapping**: Driver/Technician/HostSiteManager are entity-backed — fixtures thread `make_driver_headers(driver["id"])` etc. into ownership-gated calls (arrive/complete, cert author/confirm, dispute). The verify-SoD test uses an allowed role (SiteClerk) carrying the driver's id to isolate the SoD check. Session-resolve SoD uses `make_admin_headers("clerk-1")` since SoD compares recorded `clerk_id`, not roles.
- **Clock discipline**: startup default 2026-05-01 used as the implicit business date; clock advances via `POST /_clock/set_current_utc` only where a test's date arithmetic requires it (RECERT_DUE flips, closed periods, planned arrival dates).
- **OCC threading**: `add_policy`/`create_restock_run` fixtures always re-read the site's current version; stale-version tests pin the pre-write version deliberately.
- **Priority-pair instances** (rule 5) are legitimate because PRD §2.7 states the fourteen-stage first-failure order verbatim; each gets the dual-failure test plus one isolated-single-failure test.

## Step 6: Generate Implementation — 2026-08-10T12:12:00.000Z

Implementation complete and verified. All files are in `/home/ubuntu/github/CodingPRD/tasks/task_0988_propane_cylinder_exchange_refill/workspace/implementation/`.

## File inventory

- `start.sh` — guarded launcher (no-op pip install when flask importable; `exec python3 app.py`)
- `requirements.txt` — `flask>=2.2`
- `app.py` — Flask entry, blueprint registration, envelope-shaped error handlers (404/405/catch-all)
- `db.py` — in-memory dict stores (12 entities), logical clock (default `2026-05-01T00:00:00Z`), per-site sale-seq counters, `new_entity`/`touch` (version+1, updated_at refresh on every mutation incl. cascades)
- `errors.py` — all 33 catalog error IDs + `ApiError`
- `response.py` — envelope: `meta{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}`, `response_type`, `data`; error body `{error_id, message}`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, six roles, role gating
- `util.py` — strict body field validators (ERR_VALIDATION), Decimal weight/cents helpers (ROUND_HALF_UP), ISO date/instant parsing, year addition, `limit`/`offset` pagination (default 10, 1..100, else 400), creation-order sort
- `services/core.py` — cage counts, reorder floor (ceil(par/2)), sales posture, current-policy window match, half-open overlap, issue/depot selectors (certified_on ASC, created_at ASC), cash-event aggregation, session expected-cash refresh, serializers (computed fields on read)
- `routes/admin.py` — clock sweep, sites CRUD+OCC+status machine, policies (+supersede clipping), drivers, technicians
- `routes/cylinders.py` — registration (clerk FLEET → 403, CUSTOMER-with-site → 400, serial uniqueness), quarantine/release
- `routes/sales.py` — exchange orders (create/complete/void/refund, idempotency per clerk), refill tickets (weigh/reweigh/fill/close/void)
- `routes/compliance.py` — certification records (PASS immediate; CONDEMN two-signature), leak reports (confirm cascade, resolve with re-inspection evidence, false-alarm)
- `routes/logistics.py` — restock runs (create+supersede+forecast, dispatch DOT gates, arrive/complete/verify/cancel)
- `routes/finance.py` — commission statements (finalize/dispute/pay loop), reconciliation sessions (count/recount/escalate/resolve)

## Endpoint count

**65 endpoints** implemented — the complete PRD §4 table (13 resource groups + clock).

## State machines

All 12 implemented: HostSite (ACTIVE↔SUSPENDED→DECOMMISSIONED w/ emptiness+open-run gates), Cylinder cert (CERTIFIED↔RECERT_DUE via sweep/PASS; CONDEMNED terminal via two-signature) and fill (FULL/EMPTY/QUARANTINED incl. transit/site/depot placement), ExchangeOrder (DRAFT→COMPLETED→REFUNDED, DRAFT→VOIDED w/ MANUAL/SAFETY), RefillTicket (OPEN↔WEIGHED reweigh loop→FILLED→CLOSED, void only pre-fill), CertificationRecord (RECORDED/PENDING_SECOND→CONFIRMED/REJECTED), LeakReport (REPORTED→CONFIRMED→RESOLVED / FALSE_ALARM, with cage-quarantine + sales-block + auto-void cascade), RestockRun (DRAFT→DISPATCHED→IN_PROGRESS→COMPLETED→VERIFIED, CANCELLED from DRAFT/DISPATCHED w/ cylinder release, DRAFT supersede), CommissionStatement (DRAFT↔FINALIZED↔DISPUTED loop→PAID), ReconciliationSession (OPEN→BALANCED/VARIANCE_FLAGGED→recount loop / ESCALATED→RESOLVED), Driver/Technician (ACTIVE↔SUSPENDED).

## Calculations

- Certification expiry (12y initial, 5y VISUAL, 7y HYDROSTATIC; strictly-greater sweep)
- Swap charge (deposit zeroed on return; tax rounded half-up once on subtotal)
- Refill charge (max_fill = round-half-up(WC×0.42, 2); per-tier rounding before summing; tare tolerance 0.10 inclusive; overfill equality allowed)
- Commission settlement (GROSS/NET variants; marginal tier walk in sale_seq order; per-sale half-up rounding before summing; leak penalty 25000×count; net floored at 0)
- Reconciliation expected cash (BOOK/PHYSICAL baselines; inclusive 500-cent flag threshold)
- Cage counts (FLEET/at-site/not-in-transit/not-CONDEMNED), restock alert (inclusive), sales posture
- restock_suggested_qty (14-day half-open trailing window, exact-rational average, ceil forecast, cage-free-space clamp)
- Driver payload check (37/17 lbs, inclusive bound)

## Verification done

Booted via `bash start.sh` on `PORT`; ~75 scenario assertions pass covering: every error catalog entry exercised in situ (401/403/404/422-ref/400/412/402/409 variants), tax/tier/commission arithmetic, both commission bases, variance boundary (499 vs 500), PHYSICAL baseline carry, forecast math, supersede clip, RECERT_DUE visible-in-count-but-not-selector, leak cascade auto-voids, two-signature SoD, and per-test isolation (create entity → kill → relaunch via start.sh → store empty, no pip rerun).

## Interpretation decisions (PRD admitted multiple readings)

1. **Stage-order conflicts (§2.7 vs §3 narratives)**: followed §2.7's fixed 14-stage order. Concretely: fill checks CONDEMNED→QUARANTINED (stage 7) before RECERT_DUE (stage 8), though §3.4 lists NOT_CERTIFIED before QUARANTINED; dispatch checks CERT_EXPIRED→PAYLOAD (stage 9) before ROUTE_CONFLICT→EMPTY_ROUTE→DEPOT_STOCK_LOW (stage 11), though §3.6 narrates route-conflict before payload; technician ACTIVE/FULL gating on confirm/reject treated as stage-2 authorization (before path/state) per §2.7 stage 2.
2. **Site ACTIVE gate** applies only to sales creation + dispatch (PRD §3.3/§3.4 name creation explicitly); complete/close/refund are not gated on site status.
3. **Idempotency** checked at stage 11 position (after refs/state/safety/posture, before NO_ACTIVE_POLICY); replay returns the original resource with 201; payload = (site_id, returned_cylinder_id) / (site_id, business_date).
4. **expected_cash_cents** is refreshed on cash events only for OPEN/VARIANCE_FLAGGED sessions (ESCALATED/BALANCED/RESOLVED frozen), and always recomputed at count/recount.
5. **Statement period length** = inclusive calendar-day count (end−start+1 ≤ 62).
6. **Unknown technician identity** (X-User-ID not a registered Technician) on cert endpoints → ERR_FORBIDDEN.
7. **Site PATCH with status equal to current** → ERR_INVALID_STATE (only enumerated transitions allowed); any PATCH on a DECOMMISSIONED site → ERR_INVALID_STATE (terminal lockdown). Driver/technician PATCH status is unconstrained (no illegal transitions declared).
8. **Fill with no current policy** → ERR_NO_ACTIVE_POLICY (rates cannot be pinned; PRD silent).
9. **Missing/negative inputs**: negative payment/counts → ERR_VALIDATION; out-of-range limit/offset → ERR_VALIDATION; invalid query filter values are treated as match-nothing (lenient).
10. **`note?` on cylinder quarantine and session escalate** accepted but not stored (no such entity field exists).
11. **Clock output** normalized as `YYYY-MM-DDTHH:MM:SS[.mmm]Z` (fractional only when nonzero); clock may be set to any instant (PRD never forbids backward movement).
12. **Weigh/reweigh order of tare checks**: stamped-tare deviation checked before pre_weight≥measured (narrative order); both ERR_TARE_MISMATCH.
13. **Return-absorption** sets owner_kind=FLEET, current_site_id=site, fill_status=EMPTY unconditionally (in_transit untouched); quarantined returned cylinders are not rejected (scaffold stage-7 lists only the condemned check for exchange creation).

## Step 7: Parallel 8-Round Stability Sweep — 2026-08-10T12:23:00.000Z

Ran `sweep.sh` (8 concurrent `prd-bench-local-run --isolation per-test-server` rounds over all 98 tests, per-round free-port allocation). **All 8 rounds: 98/98 passed, 0 failed, 0 errors, 0 skipped** (~121 s per round). Union of failing tests across rounds = empty. No flakiness surfaced; no test deletions, no test_helpers fixes, no implementation fixes required. Task is stable and complete.

Subagent verbatim summary:

- **Iterations run:** 1 (single 8-round parallel sweep; all rounds ran to completion, ~121 s each)
- **Tests deleted:** none
- **Fixes applied to `test_helpers/`:** none
- **Fixes applied to `test_suite/`:** none
- **Fixes applied to `implementation/`:** none

All 8 concurrent rounds of the stability sweep passed 98/98 tests with 0 failures, 0 errors, and 0 skipped (verified directly in every `results.${i}.json`, i = 1..8, at `/home/ubuntu/github/CodingPRD/tasks/task_0988_propane_cylinder_exchange_refill/workspace/implementation/`). The union of failing tests across rounds is empty — no flakiness, no race windows, no fixture ordering issues surfaced. The implementation, test suite, and test helpers are mutually consistent and PRD-faithful as generated; the diagnostic loop terminates clean on the first iteration.

## Step 8: Finalize PRD — 2026-08-10T12:25:00.000Z

SKIPPED per skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — PRD.md already determined every behavior the implementation exhibits. No subagent spawned.

## Step 9: Complete PRD — 2026-08-10T12:40:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_0988_propane_cylinder_exchange_refill/workspace/PRD_COMPLETED.md` is written (source: `PRD.md`; no `PRD_FINALIZED.md` existed).

**Size delta:** PRD.md 320 lines / 58,263 chars → PRD_COMPLETED.md 324 lines / 62,325 chars (+4 lines, +4,062 chars).

**Counts:** 26 ambiguity-pins, 3 mismatch-revisions (29 changes total).

Changes (section — insert|revise — ambiguity|mismatch — what — impl ref):

- §2.1 — insert — ambiguity — Driver may read only their own driver record — routes/admin.py:331
- §2.1 — insert — ambiguity — Technician may read only their own technician record — routes/admin.py:380
- §2.2 — insert — ambiguity — undefined path/unsupported method → ERR_NOT_FOUND (404) before any staged check; non-object JSON body → ERR_VALIDATION; unparseable JSON treated as empty body — app.py:35-48, util.py:12-18
- §2.3 — insert — ambiguity — non-integer/out-of-range limit/offset → ERR_VALIDATION — util.py:189-214
- §2.3 — insert — ambiguity — created_at ties broken by creation sequence — util.py:219-220
- §2.3 — insert — ambiguity — `has_more` true exactly when offset + returned items < total_count — response.py:25
- §2.4 — insert — ambiguity — clock parser accepts offset-bearing instants (normalized to UTC) and bare dates (midnight UTC) — util.py:136-149
- §2.4 — insert — ambiguity — client-supplied dates must be exact YYYY-MM-DD else ERR_VALIDATION — util.py:98-108
- §2.5 — insert — ambiguity — client cent amounts and physical counts must be non-negative integers else ERR_VALIDATION — util.py:45-53, sales.py:145/380, finance.py:346-348
- §2.5 — insert — ambiguity — supplied weights stored exactly as supplied; half-up 2dp rounding governs computed weights only — routes/cylinders.py:34-39, routes/sales.py:226
- §2.7 — insert — ambiguity — ERR_VALIDATION sits outside the 14 stages (at parse time, after stages 1–2 or after stage 3 when a path resource is resolved first); resource-dependent authorization runs immediately after stage 3 — routes passim
- §2.7 — insert — ambiguity — site-ACTIVE/sales-posture gates bind sale intake and dispatch only; complete/weigh/fill/close/void/refund do not re-evaluate them — routes/sales.py:139-212, 290-407
- §2.9 — insert — ambiguity — idempotency payload identity = site_id+returned_cylinder_id (orders) / site_id+business_date (sessions); replay returns 201 with the original — sales.py:76-81, finance.py:266-271
- §3.1 — insert — ambiguity — patch revalidates merged par_level_full ≤ cage_capacity_cylinders — routes/admin.py:150-153
- §3.1 — insert — ambiguity — sites list filterable by `status` — routes/admin.py:107-109
- §3.1 — insert — ambiguity — supplied effective_to must be strictly after effective_from else ERR_VALIDATION — routes/admin.py:210-211
- §3.1 — insert — ambiguity — supersede_current with no current policy clips nothing, proceeds as ordinary create — routes/admin.py:226-234
- §3.2 — insert — ambiguity — whole-year advances clamp Feb 29 → Feb 28 in non-leap target years — util.py:160-167
- §3.2 — insert — ambiguity — acting/second-signature technician must be a registered ACTIVE technician else ERR_FORBIDDEN — routes/compliance.py:38-43
- §3.2 — insert — ambiguity — cylinder list filters enumerated (current_site_id, in_transit_run_id, fill_status, cert_status, owner_kind) — routes/cylinders.py:83-86
- §3.2 — insert — ambiguity — cert-record note defaults to empty string; record list filters enumerated (cylinder_id, technician_id, confirmer_technician_id, outcome, status) — routes/compliance.py:58, 126-129
- §3.3 — insert — ambiguity — returned cylinder accepted with no owner_kind/fill_status/quarantine check beyond not-condemned — routes/sales.py:60-71
- §3.5 — insert — ambiguity — leak-report note defaults to empty string — routes/compliance.py:192
- §3.5 — revise — mismatch — removed "an optional note may be attached" from officer cylinder quarantine (impl stores no note on cylinders) — routes/cylinders.py:92-101
- §3.6 — revise — ambiguity — forecast counts only orders currently in COMPLETED status (refunded excluded) — routes/logistics.py:43-50
- §3.6 — revise — mismatch — forecast day multiplier floored at zero whenever planned_date is today or earlier (PRD said "when planned for today"; impl max(0, …) floors past dates too) — routes/logistics.py:52
- §3.6 — insert — ambiguity — delivered subset chosen oldest-certified first; picked-up empties chosen oldest-created first — routes/logistics.py:218-237
- §3.6 — insert — ambiguity — run reads/listings are not owner-scoped; driver ownership gates only arrive/complete — routes/logistics.py:115-133 vs 187, 203
- §3.8 — revise — mismatch — removed "optionally attaching a note" from session escalation (no note field stored) — routes/finance.py:390-400

Everything else in the implementation — the 14-stage error ordering, all state machines, the tiered refill/commission rounding doctrine, OCC coverage, cage-count derivation, selectors, reconciliation baselines and thresholds, error catalogue codes/HTTP statuses, and the §4 role table — was verified against the PRD and required no change.
