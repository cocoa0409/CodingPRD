# Worklog — task_1092_co_living_by_the_room_rental

## Step 1: Create task directory — 2026-07-24T00:00:00.000Z

Pre-assigned folder used as-is (Step 1 scan skipped per orchestrator instruction). Created `tasks/task_1092_co_living_by_the_room_rental/workspace/`.

## Step 2: Generate Scaffold (Expert) — 2026-07-24T03:42:00.000Z

All three artifacts are written and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1092_co_living_by_the_room_rental/`):
- `SCAFFOLD.yaml` (2451 lines) — §1.0–§1.7, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1768 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (3526 lines) — single key `scaffold_corner_design`

**Lint verdict (verbatim):**
```
Coverage
  §1.5 endpoints declared:    46
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     59
  Calls scanned (§1.8+§1.9):  807

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Counts**
| Item | Count |
|---|---|
| Entities | 12 (Host, House, Room, Member, Application, ScreeningReport, Membership, Invoice, Payment, HouseRuleIncident, MaintenanceTicket, Payout) |
| State machines | 9 |
| Concurrency rules (OCC) | 2 |
| Calculations | 10 |
| Validations | 32 (priority-ordered) |
| Endpoints | 46 |
| Errors | 47 |
| Roles | 6 |
| §1.8 instances | 18 (9 rules × 2) |
| §1.9 instances | 68 total (59 with recipes + 9 `excluded_because` stubs) across all 9 guide sections |

**Non-linear machines:** cyclic — `Membership.tenancy_status` (ACTIVE↔NOTICE_GIVEN via auto-rescind), `Membership.billing_status` (CURRENT↔PAST_DUE), `Room.occupancy_state` (VACANT→RESERVED→OCCUPIED→NOTICE_PENDING→VACANT, plus VACANT↔OUT_OF_SERVICE), `HouseRuleIncident` (UPHELD↔DISPUTED, bounded by MAX_DISPUTE_ROUNDS), `Application` (CONDITIONAL→SUBMITTED revision loop); parallel — Membership's two axes on one row; posture-driven — `House.compliance_posture` (OPEN/RESTRICTED/FROZEN); branching — `Application` decision fork and `Invoice`.

**Key design notes**
- Profile: `temporal_windowing` × `compliance_audit`, `flat` topology, `segregation_of_duties` role model, `immediate` consistency.
- Dual variants on different domains: move-out proration (whole-period block 39000 vs daily 22284) and payout settlement (accrual 66412 vs cash 36312).
- Combinatorial modes (b) and (c): platform fee rounded per-invoice-then-summed (7974 vs 7973 sum-then-round); late-fee tier keyed on `subtotal_cents` not `total_amount_cents` (2500 vs the trap value 4000).
- Two overlap semantics on different resources: Room closed-date intervals + `TURNOVER_BUFFER_DAYS` gap vs House half-open `[visit_start, visit_end)` windows with aggregate capacity 2.
- Two conserved quantities: `Membership.balance_due_cents` (fee assess/waive) and the House room-state partition (`total == vacant+reserved+occupied+notice_pending+out_of_service`).
- Logical clock `POST /co-living/_clock/set_current_utc` with the mandated `2026-05-01T00:00:00Z` startup default.
- Every formula-derived assertion literal was computed in Python before being written (income bar 324999, utility shares 14000/7000/60000, proration 5571×4=22284, credit 5357, payout 7974/3189/52621/55810/66412/36312).
- One correction made during authoring: `ERR_SCREENING_MISSING` was unreachable (the state gate at priority 10 always pre-empted it), so priority 12 was repurposed into a live cross-entity gate (invoices only for ACTIVE/NOTICE_GIVEN tenancies) and the dead error removed. All 47 remaining errors are both validation-referenced and exercised by at least one design instance.

**Orchestrator post-checks:** all 3 files `yaml.safe_load` cleanly; every named constant (`GRACE_DAYS`, `MIN_NOTICE_DAYS`, `TURNOVER_BUFFER_DAYS`, `STRIKE_*`, `LATE_FEE_TIER*`, `PLATFORM_FEE_RATE`, `PAYOUT_RESERVE_RATE`, `SLA_HOURS_BY_SEVERITY`, …) has a declared value in SCAFFOLD.yaml — no undeclared-constant patch needed.

## Step 3: Copy shared files — 2026-07-24T03:43:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1092_co_living_by_the_room_rental/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-24T03:52:00.000Z

All hard contracts pass. PRD documents all 46 endpoints and all 47 errors.

- Field coverage (Contract 1): PASS — all 115 required names appear verbatim in backticks.
- Rule coverage (Contract 2): PASS — 7 state machines, 10 calculations, 32 validations (priority-ordered as a 32-step precedence chain in §2.5), both OCC rules (412), depth-4 compliance cascade, NONPAYMENT auto-rescind back-edge.
- §3 path purity (Contract 3): PASS — no HTTP methods/paths in §3.
- **PRD line count:** 395; **Endpoints documented:** 46/46; **Errors documented:** 47/47.

Scaffold gaps/ambiguities resolved:
- `billing_status` second axis + `Room`/`House.compliance_posture` posture machine evolve independently of `tenancy_status`; each given own narrative home (§3.6 billing, §2.8 posture) with explicit independence.
- Provisional (Variant A whole-period) vs final (Variant B daily) proration rendered with equal density in §3.8 incl. "strictly smaller when occupied_days < period_days" and matching-invoice selection rule.
- Per-invoice-then-sum rounding for platform fee, three-independent-roundings for maintenance credit stated as binding (§2.6 + §3.9/§3.10).
- Append-only `ScreeningReport`/`Payment` (common_fields:false) documented as id/created_at only (no updated_at/version).
- Turnover ratio exact-rational comparison (`2 * notice_pending > total`, strict) and half-open 90-day strike / 30-day incident windows translated precisely.

## Step 6: Generate Implementation — 2026-07-24T04:10:00.000Z

Complete Python + Flask impl at `workspace/implementation/` (13 files).

**Files:** start.sh (foreground, $PORT, 0.0.0.0, guarded pip install), requirements.txt (flask), app.py (X-User-ID/X-User-Role auth via before_request, ApiError handler, blueprint registration), state.py (in-memory dicts + logical clock default `2026-05-01T00:00:00Z`, id/seq gens, no seeding), helpers.py (error catalogue, response envelope, ISO-8601/date parse+format, half-up + ceil rounding, body/pagination validators, RBAC/ownership), domain.py (house counts & compliance posture frozen>restricted>open, strike standing, balance-due, invoice assembly, both proration variants, maintenance credit, serializers), routes_core/applications/memberships/billing/incidents/maintenance/payouts.py.

**Endpoints implemented: 46** (all registered).

**Correctness points:** precedence chain (§2.5) enforced per-endpoint in 1–32 order; timestamps from logical clock with exactly `.000Z`, current_utc echoed verbatim (dodges wall-clock/format-mismatch bug), occupancy/billing dates as `YYYY-MM-DD`; Decimal money math (independent roundings, ceil for utility divisions monthly-then-weekly, half-up daily proration ×once); parallel tenancy×billing axes, depth-4 compliance strike cascade, NONPAYMENT auto-rescind back-edge, OCC on room/house versions, SoD, dual-basis payout (accrual project vs cash release), append-only ScreeningReport/Payment (id/created_at only).

**Boot verification:** boots cleanly on PORT=8199, 401 for unauthenticated; e2e flow (clock→host→house→room→member→application→screening→approve→membership→move-in→invoice) + late-fee assess/waive neutrality + move-out proration produced correct values (subtotal 110000, deposit 20000, tier-3 fee 4000, daily 3667×15=55005, proration −54995).

## Step 7 (RESUME): Pre-sweep partial-write guard — 2026-07-24T11:18:00.000Z

Resumed pipeline at Step 7. Partial-write guard PASSED before sweeping:
- py_compile clean on all implementation/*.py.
- Route decorators (`@bp.<verb>`) = 46; registered url_map rules (non-static) = 46; scaffold endpoints = 46. All equal → no partial-write gap.
- Boot smoke on PORT=8391: unauthenticated POST /co-living/hosts → 401; authenticated POST /co-living/_clock/set_current_utc → 200 with correct envelope (current_utc echoed verbatim `2026-05-01T00:00:00Z`, api_request_timestamp `.000Z`).
- test_suite: 8 modules, 63 test functions.
Proceeding to Step-7 8-round stability sweep (run as 4 waves of 2 for host-saturation mitigation — 4 sibling tasks sweeping concurrently on this 8-core host).

## Step 7 (RESUME): 8-round stability sweep — 2026-07-24T11:27:00.000Z

Sweep run as 4 waves of 2 rounds (host-saturation mitigation). Independently re-parsed all 8 results.N.json: every round 63/63 passed, 0 failed / 0 skipped / 0 xfail / 0 errors. Grep confirms exactly 63 `"status": "passed"` per round, no other status tokens.

**Iterations run:** 2 sweeps (initial + verification).
**Tests deleted:** None.
**Fixes to test_helpers/:** None.
**Fixes to test_suite/:** None.
**Fixes to implementation/:**
- `routes_core.py`, `create_room()` (POST /co-living/rooms): the Host-ownership check treated a non-existent `house_id` as an ownership failure (`if house is None or house["host_id"] != g.user_id: raise ERR_NOT_RESOURCE_OWNER`), so `test_create_room_under_unknown_house_returns_house_not_found` got `ERR_NOT_RESOURCE_OWNER` instead of `ERR_HOUSE_NOT_FOUND`. Changed to `if house is not None and house["host_id"] != g.user_id`, letting a missing house fall through to step-6 body-FK resolution (`find_or_404` → `ERR_HOUSE_NOT_FOUND`).

**Diagnosis:** PRD §2.5 precedence chain places ownership (step 4, ERR_NOT_RESOURCE_OWNER) before body-FK resolution (step 6, which explicitly names room-creation → ERR_HOUSE_NOT_FOUND). Ownership (§2.1) compares the owning host_id "on the house behind a room" to X-User-ID — a non-existent house has no owning host_id, so house-exists-but-unowned vs house-doesn't-exist are disjoint world-states that can never both be violated. Uniquely-determined against PRD as an implementation bug (not test/PRD-silence). → Step 8 runs (1 impl fix).

## Step 8 (RESUME): Finalize PRD — 2026-07-24T11:29:00.000Z

Step 7 had 1 implementation fix → Step 8 ran. Created workspace/PRD_FINALIZED.md (395 → 395 lines, one line's prose extended in place).

**Change:** §2.5 precedence chain (item 4) — revise — appended a room-creation-specific clause: the Host ownership check fires only when `house_id` resolves to an existing house owned by another host; a `house_id` resolving to no house skips the ownership check and falls through to step-6 FK resolution → `ERR_HOUSE_NOT_FOUND`. (implementation/routes_core.py:131-143)

**Why needed:** the chain places ownership (step 4) before body-FK resolution (step 6); the natural reading yields ERR_NOT_RESOURCE_OWNER for a missing house (the pre-fix behavior). PRD did not uniquely determine impl's ERR_HOUSE_NOT_FOUND, so pinning was warranted.

**NO-NEW-MISMATCH check:** impl is non-uniform — create_incident/create_ticket return ERR_NOT_RESOURCE_OWNER for a missing parent membership, unlike create_room. Edit scoped strictly to "on room creation specifically"; no general "missing parent defers to FK" wording (would mis-describe incident/ticket paths). Those paths stay consistent with the chain as written; no further edits.

## Step 9 (RESUME): Complete PRD — 2026-07-24T11:34:00.000Z

Full PRD-vs-implementation scan. PRD_FINALIZED.md (395 lines / 69,263 chars) → workspace/PRD_COMPLETED.md (395 lines / 70,061 chars, +798 chars, 0 net lines). Ambiguity-pins: 5. Mismatch-revisions: 0. PRD was unusually complete — rounding order, half-open/closed intervals, error precedence, OCC bumps, cascade hops, dual-basis payout, Variant A/B proration, `.000Z`/`YYYY-MM-DD` shapes all already uniquely pinned.

5 silences closed:
- §2.4 Logical clock — clock-set response echoes `current_utc` verbatim (raw to_iso8601, not re-normalized) — routes_core.py:24.
- §3.1 Rooms — room revision fields all optional/partial (omit/null → unchanged; supplied rate must be > 0) — routes_core.py:175-192.
- §3.2 Applications — fresh application `monthly_equivalent_cents`/`required_income_cents` are 0 until first screening — routes_applications.py:64-66.
- §3.4 Move-in — early move-in (clock date < move_in_date) → ERR_INVALID_MEMBERSHIP_STATE at position-10 state gate before posture gate — routes_memberships.py:127-128.
- §3.6 Fee-adjustment ASSESS — assess against non-OPEN/PARTIAL invoice (e.g. PAST_DUE after waive-to-zero) → ERR_LATE_FEE_ALREADY_ASSESSED — routes_billing.py:191-192.

## DONE — 2026-07-24T11:34:00.000Z
Pipeline complete. All 8 stability-sweep rounds 63/63 (independently re-parsed, 0 skip/xfail/error). workspace/PRD_COMPLETED.md present. Steps 7→8→9 finished.
