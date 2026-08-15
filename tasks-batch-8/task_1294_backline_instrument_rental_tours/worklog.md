# Worklog — task_1294_backline_instrument_rental_tours

## Step 1: Create task directory — 2026-08-12T00:00:00.000Z

Task directory `tasks/task_1294_backline_instrument_rental_tours/` and `workspace/` were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per invocation instructions.

## Step 3: Copy shared files — 2026-08-12T00:00:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1294_backline_instrument_rental_tours/workspace/INSTRUCTION.md`. (Executed out of order, concurrent with Step 2, since it has no dependency on the scaffold.)

## Step 2: Generate scaffold — 2026-08-12T20:10:00.000Z

(RESUME RUN — previous run terminated before Step 2 produced output; re-ran Step 2. User difficulty directive: "harder than expert level" — applied to §1.8/§1.9 depth/breadth only, scenario verbatim.)

Final lint verdict:

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1294_backline_instrument_rental_tours/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (scenario verbatim, `backline-tour-rental` domain, `/backline` prefix)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Counts:**
- Entities: **14** (Artist, Tour, TourStop, RiderLine, GearModel, GearUnit, ReservationLine, Shipment, ShipmentLine, FlightCase, PartnerVendor, CrossRentalRequest, MaintenanceTicket, DamageClaim)
- State machines: **12** (incl. two cyclic: RiderLine SOURCED↔SUBSTITUTION_PENDING revision loop, MaintenanceTicket IN_PROGRESS↔AWAITING_PARTS, plus PartnerVendor reinstatement cycle)
- Endpoints: **95** (incl. `/_clock/set_current_utc` with pinned default 2026-08-01T00:00:00Z, and a deposit top-up business endpoint)
- Calculations: **9** | Validations: **16** | Errors: **17** | Roles: **5** | OCC concurrency rules: **3**
- §1.8 instances: **18** (2 per rule × 9 rules), 506 total calls lint-scanned
- §1.9 instances: **27** (26 active + 1 `excluded_because` stub), covering entities / state machines / calculations / validations / endpoints / errors / RBAC / cross-cutting layers / consistency model

**Design notes for the worklog:**
- Archetype: temporal windowing (half-open `[start,end)` gear availability with a 1-day cross-city transit buffer that *breaks* pure adjacency semantics) + quota/allocation (tiered marginal deposit holds).
- Dual-variant pairs span different domains: ReservationLine fee (forward-looking quote vs chronological settle; diverges via settle-time risk_score, late blocks, shortage credit) and Artist (recompute-from-scratch risk score vs incrementally-reconciled deposit balance — the §1.9 waive case proves the difference).
- Rounding-order contrast is pinned deliberately: fee quote = round-per-component-then-sum; deposit = sum-then-round; both verified by executing the formulas (500000/625000/840000/221664; tiers 40000/47500/55000/85000).
- Deposit semantics pinned: top-up credits balance, sourcing debits by held amount, cancel/settle compensates — required adding a real business endpoint (`POST /artists/{id}/deposit-topups`) via the §1.5 priority ladder so STANDARD-tier artists can source at all.
- Segregation of duties on DamageClaim (filer cannot assess) with `filed_by_user_id` server-stamped from X-User-ID; cross-vendor ownership scoping for the entity_backed PartnerVendorRep role.
- Fixes applied during self-review: FlightCase RETIRED enum was unreachable (added retire transition + endpoint); dispatch precondition relaxed from per-unit shipment-line booking to tour-level shipment presence (cross-rental holds no in-house unit); quantity-2 rider lines split into quantity-1 lines with captured `gear_unit_id` to remove selector ambiguity; list-order-dependent captures replaced with per-reservation filtered queries.

## Step 4: Generate PRD — 2026-08-12T20:31:00.000Z

**File written:** `/home/ubuntu/github/CodingPRD/tasks/task_1294_backline_instrument_rental_tours/workspace/PRD.md` — 372 lines. (The withheld files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened.)

**Section overview:**
- **§1 Introduction** — 2 paragraphs, business-context angle (touring backline pain points → system scope); the `/backline` mount is declared here.
- **§2 Global Specifications** — 11 subsections: RBAC with per-role identity prose (4 opaque roles + `PartnerVendorRep` entity-backed via `partner_vendor_id`), the verbatim §2.2 envelope block (byte-identical to the canonical source, verified by diff), pagination, resource identity/timestamps/versioning, logical clock + half-open window semantics (clock default `2026-08-01T00:00:00Z`), cents/rounding (per-component-vs-sum-then-round contrast pinned), the artist deposit ledger, serviceability gates (40/30 boundaries), cascade discipline, OCC (all 3 rules with exact `occ_field` names + `ERR_STALE_VERSION`/412), and a nested-path-resolution + 16-gate validation-order list with per-endpoint orderings (e.g., serviceability → availability → window → deposit on sourcing; deposit before insurance on activation).
- **§3 Business Logic** — 9 subsections organized by operational timeline: artist onboarding/risk → tour build/activation → sourcing/availability/quote → substitutions/shortages → cartage/flight cases → dispatch/check-in/maintenance gate → damage claims/SoD → partner vendors/cross-rental → settlement/tour completion.
- **§4 Endpoint table** — 95 rows, 4 columns only (Method, Path, Description, Authorized Role(s)).
- **§5 Error catalogue** — 17 errors, 2 columns only.

**Design decisions worth recording (worklog notes):**
- *Scattering strategy:* endpoint inputs deliberately split across subsections — e.g., sourcing's `origin_city_code`/`dest_city_code`/dates live in §3.3 while `use_cross_rental`/`partner_vendor_id`/`vendor_rate_cents_per_day` live in §3.8; inspect's `damage_present` in §3.6 while `assessed_severity`/`repair_estimate_cents` live in §3.7; OCC fields anchored in §2.10 and re-referenced in §3.2/§3.4/§3.9.
- *Constants embedded with unit glosses:* deposit tiers rendered as "200,000 cents — the first two thousand dollars" style, with worked boundaries 40,000 / 85,000 cents preserved; late fee as "one-and-a-half times the daily base rate per started 24-hour block"; commission as basis points over ten thousand.
- *Zero-Silence (Contract 2) coverage:* all 74 state transitions verified to have from/to states named in shared narrative context; all 9 calculations rendered as reconstruction-safe prose (no operators, no fuzzy words — scanned mechanically); all 16 validations mapped to their `error_id` in prose with explicit priority ordering; sibling branches rendered symmetrically (DRAFT vs SOURCED reservation cancel, ASSESSED vs DISPUTED charge/waive with their different actors, DRAFT vs ACTIVE tour cancel).
- *Fidelity judgment calls:* the Tour field description mentioned "CONFIRMED+DRAFT" reservation lines for the projected fee, but the `ReservationLine` enum has no `CONFIRMED`; I followed the activation side-effect ("DRAFT+SOURCED"), which is the enum-consistent reading. The scaffold's counterintuitive priority-16 placement of `ERR_INVALID_REQUEST` (shape checks last) was rendered faithfully rather than "corrected."

**Contract reports:**
- Contract 1 (Field-Name Coverage): 83 required identifiers (entity fields + endpoint inputs + path/query params), 83 present, 0 missing — **PASS**
- Contract 2 (Rule Coverage): 16/16 validations with priority expressed, 3/3 OCC rules (endpoint + `expected_*` field + error id + status), 74/74 transitions, 9/9 calculations, 17/17 errors in prose, structured field defaults/initials covered, sibling groups symmetric — **PASS**
- Contract 3 (§3 Path Purity): 526 backticked tokens scanned in §3, 0 path tokens, 0 bare-method tokens, 0 method+path combos — **PASS**

## Step 5: Generate unit tests — 2026-08-12T21:05:00.000Z

(Launched concurrently with Step 6 in a single message.)

Generation complete. All audits green: syntax OK, 63 tests, every docstring quote greps verbatim in PRD.md, every test ends with exactly one resolving `Design:` tag as its last line, no skip/xfail markers, test files import only from `test_helpers`.

## Files written

**test_helpers/** (9 files): `types.py` (18 status/role enums + 14 entity TypedDicts), `api_client.py` (`ApiClient(GenericApiClient)`, one method per PRD endpoint, ~70 methods), `api_errors.py` (17 error IDs + HTTP map registered via `set_error_http_status_map`), `constants.py` (serviceability gates, deposit tiers, zone regions, severity weights + `expected_deposit_hold`/`zone_multiplier`/`expected_quoted_fee` helpers), `factories.py` (payload factories, input fields only), `test_users.py` (opaque-role header constants + mandatory `make_vendor_rep_headers(vendor_id)` for the `entity_backed:PartnerVendor` role), `assertions.py` (per-entity assertions + deposit invariant checker), `fixtures.py` (~25 composites incl. scenario builders: quote/settlement divergence, rounding contrast, substitution cycle, load-out cascade, vendor-suspend pair, stage guard, cross-rental-fulfilled, overlap/transit scenes, maintenance-gate boundary pair, overage pair, SoD scene), `__init__.py` barrel.

**test_suite/** (9 files): `conftest.py` + 8 test files, 63 tests total.

## Test counts

- **Queue A (Difficulty): 18/18 instances, 36 tests (exactly 2 each)** — dual_variant_calc ×2, combinatorial_formula ×2, non_linear_state_machine ×2, transitive_cascade ×2, priority_pair ×2, boundary_precision ×2, cross_entity_state_dependency ×2, resource_temporal_overlap ×2, compensating_invariant ×2.
- **Queue B (Corner): 27/27 non-stub instances, 27 tests (1 each)** across all 9 sections.

## Skipped instances

- `Corner/calculations/fee_calculation_correct_result_excluded` — `excluded_because:` stub; its assertion is owned by `rental_fee_quote_multi_input_nonlinear` (cross-reference verified to resolve). Not translated, per spec.

No other gaps: all 45 non-stub instances passed the PRD-first two-condition filter.

## Design decisions worth recording

1. **Capacity and flight-case checks asserted at booking, not loading.** PRD §3.5 states both constraints are "enforced both at booking and again at loading", and `weight_kg`/`flight_case_id` exist only on the booking payload — so a PRD-faithful server rejects the over-capacity or case-less line at `POST /shipments/{id}/lines`. The corner recipes' booking steps would already fail; the tests assert the pinned `error_id` at the reachable point (with the equal-to-capacity boundary also covered).
2. **Substitution allowlist test adds a substitute-model unit** (absent from the recipe): gate 8 (availability) precedes gate 10 (allowlist) per §2.11, so without an available substitute unit the trigger would surface `ERR_GEAR_UNAVAILABLE`, not `ERR_SUBSTITUTION_NOT_ALLOWED`.
3. **Overage-pair top-up raised 110000 → 220000.** §3.2's activation gate ("holds … must fit within the artist's deposit balance") is ambiguous against an already-debited balance; the larger top-up keeps activation valid under every plausible reading while leaving the charge boundary (55000 vs 55001 against a 55000 hold) untouched.
4. **`version == 1` not asserted on creation** (corner instance listed it): PRD §2.4 says version "increments on every mutation" but never pins the initial value — the two-reader test fails, so only integer type / cross-read consistency is asserted.
5. **Unit release after direct reservation cancel** is asserted via §3.9's "standard compensation" definition; DRAFT-tour-cancel unit release is asserted via §2.9's verbatim "releasing any physical units the cascade unties".
6. **Late-check-in timestamps in fixtures** (e.g. 09:00 on end date) incur a 1-block late fee at settlement; no test asserts settled fees in those scenes except the divergence test, whose 36-hour / 2-block arithmetic is exact (quoted 500000 → settled 840000 = +40000 insurance at risk 60 + 2×150000 late).

## Step 6: Generate implementation — 2026-08-12T21:05:00.000Z

(Launched concurrently with Step 5 in a single message.)

All 95 endpoints implemented, compile check passes, clean-boot and reboot-isolation verified. Here is the final summary.

---

### Files written
All under `/home/ubuntu/github/CodingPRD/tasks/task_1294_backline_instrument_rental_tours/workspace/implementation/`:

| File | Purpose |
|---|---|
| `start.sh` | Executable launcher; guarded `pip install` (no-op when Flask already importable), `exec python3 app.py` in foreground, reads `$PORT` (default 10000), binds `0.0.0.0` |
| `requirements.txt` | `Flask>=3.0` |
| `app.py` | Flask entry point; registers 12 blueprints; `ApiError` → standard error envelope; 404/405 → `ERR_NOT_FOUND` |
| `db.py` | `Store` class with 14 dict tables keyed by UUID; logical clock pinned to `2026-08-01T00:00:00Z` at boot (PRD §2.5, never wall-clock) |
| `errors.py` | `ApiError` class + all 17 error-ID constants and constructors with exact HTTP statuses from PRD §5 |
| `response.py` | Success/error envelope per PRD §2.2 (`meta.api_request_id` with `req_` prefix, `api_request_timestamp` with 3 fractional digits, `response_type`, `data`); pagination fields in `meta` for lists |
| `middleware.py` | Gate 1/2: `X-User-ID`/`X-User-Role` presence + 5 declared roles; `require_roles` per RBAC matrix |
| `util.py` | ISO8601 parse (date pinned to UTC midnight vs full timestamp), day-count of half-open windows (min 1), typed field validators (`ERR_INVALID_REQUEST`), pagination (`limit` 1–100 default 10, `offset` default 0), `new_resource()` (`id`/`created_at`/`updated_at`/`version`), `touch()` (eager version bump + timestamp per §2.4), created_at-ascending sort |
| `services/calculations.py` | All 9 calculation rules: `gear_availability_window` (constraint propagation + 1-day transit buffer + same-city/days/created_at ranking, tie-break never id), `rental_fee_quote` (round-per-component then sum), `rental_fee_settlement` (late blocks at 150% rounded once, settle-time risk score, shortage credit, floor 0), `deposit_hold_rule` (marginal tiers 20/15/10%, sum-then-round once), `damage_charge_rule`, `cross_rental_settlement` (bps/10000, round once), `maintenance_cycle_gate` (projected ≥30 forces MAINTENANCE; condition ==40 passes), `artist_risk_score` (weights ×2 within 90d, trailing 365d, cap 100, recompute-from-scratch), `shortage_credit_rule` |
| `services/domain.py` | Serializers (strip `_`-prefixed internals), left-to-right lookups, `reconcile_shipment_aggregates` (eager), `create_sourced_reservation` (DRAFT→SOURCED + quote + deposit debit + unit flip + rider_revision bump), `release_reservation` (compensation: unit→AVAILABLE + deposit credit-back, optional maintenance-gate re-check), `open_maintenance_ticket`, `check_in_reservation` (cascade: AVAILABLE vs MAINTENANCE + day accumulation), `recompute_projected_fee`, `rider_line_was_shorted` (walks substitution chain) |
| `routes/*.py` | 12 blueprints: clock, artists, tours, stops, rider_lines, gear (models+units), reservations, shipments (+lines), flight_cases, vendors (+cross-rental-requests), maintenance, damage_claims |

### Endpoint count
**95 / 95** routes from the PRD §4 table implemented (verified by inventory diff).

### Design decisions worth recording
- **Internal `_`-prefixed fields** (`_start_dt`, `_end_dt`, `_checked_in_dt`, `_vendor_rate_cents_per_day`, `_substitute_gear_model_id`) hold parsed datetimes / transient state; stripped from every serialized response so no non-PRD fields leak.
- **Gate-order fidelity**: per PRD §2.11, state legality (409) fires before OCC (412) which fires before business gates; within `source`, window-sanity (start<end) is checked before candidate selection so an unserviceable-only pool reports `ERR_UNIT_NOT_SERVICEABLE` while a serviceable-but-conflicted pool reports `ERR_GEAR_UNAVAILABLE`; in `propose-substitution`, availability (gate 8) fires before the substitution allowlist (gate 10) per §3.4; in shipment line booking/loading, capacity (gate 11) fires before flight-case adequacy (gate 12).
- **OCC fields are non-optional** on the three guarded writes (missing → `ERR_INVALID_REQUEST`, mismatch → `ERR_STALE_VERSION`) per PRD §2.10.
- **Tour-cancel RBAC is state-dependent**: DRAFT cancel requires TourManager, ACTIVE cancel requires OpsManager — a wrong role for the current state returns `ERR_UNAUTHORIZED` (403), while a terminal/wrong state returns `ERR_INVALID_STATE`.
- **Damage-charge RBAC is state-dependent**: ASSESSED→CHARGED is TourManager-only; DISPUTED→CHARGED is OpsManager-only (wrong role → 403 `ERR_UNAUTHORIZED`), per PRD §3.7 prose.
- **Cross-rental `mark-fulfilled`** only transitions the linked reservation when it is still DRAFT (per the PRD's "drives the reservation from DRAFT to SOURCED" wording), so a reservation already settled is never regressed.
- **Deposit release at settle** credits `deposit_held_cents − PAID damage charges` and zeroes the hold; cancellations credit the full hold back.
- Verified by three end-to-end scripts: full rental lifecycle (quote/deposit/dispatch/ship/check-in/inspect/settle/complete), substitution OCC + deposit re-debit, cross-rental path + commission, shortage credit, maintenance gate at exactly-30 boundary, deposit-insufficiency (402), insurance-required (422), segregation-of-duties (403), duplicate SKU (409), and late-fee settlement arithmetic. Fresh-boot and kill/restart cycles confirmed state isolation (empty store, clock reset to 2026-08-01).

## Step 7: Run tests and iterate — 2026-08-12T21:45:00.000Z

All 8 rounds are clean: 63/63 passed in every round. Exit condition met.

**Iterations run:** 5 sweeps (2 functional-fix rounds, 2 infra-hardening rounds, 1 sweep aborted by co-tenant process kills on the shared host).

**Tests deleted:** None outright. One partial split per STEP 1c:
- `test_risk_score_input_set_filtering` (test_05) — removed the "waive → risk recomputes to 0" assertion. PRD §3.1 names exactly two recompute triggers verbatim ("each time one of the artist's claims is assessed and again when one is marked paid"); waive is never named as a trigger (trigger-silence / branch-asymmetric side-effect pattern; two faithful readers diverge — one recomputing only on the named triggers yields 24, not 0). Kept the fully-covered assertion (ASSESSED MAJOR within 90 days → 12×2 = 24). Feedback for unit-test-generator: the scaffold's waive transition carries no risk-recompute side effect, so the generated test over-asserted.

**Fixes applied to `test_helpers/`:**
- `fixtures.py::setup_quote_settlement_divergence` — reordered setup: the reservation under test is now sourced while the artist's risk is still 0 (before the TOTAL_LOSS damage drive + assessment), so its quote is 500000 and the settle-time divergence (840000) matches PRD §3.9's quote-time vs settle-time risk rule. Previously the claim was assessed before the sourcing, making quote-time risk already 60 (540000) — a fixture ordering bug, not an implementation bug.
- `api_client.py::ApiClient.__init__` — transport hardening only: `Connection: close` + a retrying HTTPAdapter. Per-test-server isolation restarts the API between tests; the shared keep-alive session held dead connections, surfacing as sporadic ECONNRESET on test-first POSTs. No assertion touched.

**Fixes applied to `test_suite/`:**
- `test_06_cycles_and_cascades.py` — added the missing `get_tour` import (NameError in `test_stage_blocked_on_draft_tour`; the assertion itself is PRD-faithful).

**Fixes applied to `implementation/`:**
- `services/calculations.py::gear_availability_window` — candidate pool excluded any unit not literally `AVAILABLE`, which made PRD §3.3's conflict clause dead code (sourcing flips units to RESERVED, so the clause could never fire) and broke the verbatim adjacency rule ("windows that merely touch … do not conflict"). Now only out-of-service statuses (MAINTENANCE/QUARANTINED/RETIRED) are excluded; the half-open overlap clause does temporal exclusion. Fixed `test_adjacent_window_succeeds`, `test_overlapping_window_fails`, `test_transit_buffer_shifted_window_succeeds`.
- `routes/rider_lines.py::source_rider_line` — restructured the cross-rental path per PRD §3.8: when `use_cross_rental` is set, the named vendor's eligibility is the gate (`ERR_VENDOR_NOT_ELIGIBLE` for non-APPROVED/non-covering vendors instead of the leaky `ERR_GEAR_UNAVAILABLE`), a DRAFT reservation holding no in-house unit is created (fulfillment drives DRAFT→SOURCED per PRD), and a CrossRentalRequest in REQUESTED is opened so the vendor-rep negotiation flow exists. Fixed `test_cross_rental_vendor_not_eligible` plus the five IndexError tests (`test_vendor_rep_scoped_to_own_vendor`, `test_vendor_suspend_cancels_open_requests`, `test_vendor_reinstatement_cycle_after_suspend`, both crossrental-settle tests).
- `services/domain.py` — added `create_draft_cross_rental_reservation` supporting the above.
- `routes/tours.py::cancel_tour` — DRAFT-cancel cascade now also cancels SOURCED reservations with unit release + deposit credit-back (PRD §2.9 "reaches down through … the reservations sourced for those lines, releasing any physical units" and §3.2's stop-cancel cascade covering DRAFT+SOURCED). Fixed `test_cascade_tour_cancel_releases_units`.
- `start.sh` — exec app.py via absolute path so the server argv is unique to this task; broad `pkill -f "python3 app.py"` patterns from co-tenant pipelines on the shared host (10 concurrent 8-round sweeps observed; one aborted an entire sweep at startup) no longer match this server.

## Step 8: Finalize PRD — 2026-08-12T21:48:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1294_backline_instrument_rental_tours/workspace/PRD_FINALIZED.md` is written with a minimal patch (4 in-place sentence revisions, no new sections).

**Line counts / delta:** PRD.md 372 lines, PRD_FINALIZED.md 372 lines — 0% line delta; 4 lines revised in place.

**Changes (one per bullet):**
- **§3.3** — revise — Candidate pool redefined: "currently sit in `AVAILABLE`" replaced by exclusion of out-of-service units only (`MAINTENANCE`/`QUARANTINED`/`RETIRED`); committed units stay in the pool and are excluded by the half-open overlap clause; adjacency note extended ("so the same physical unit may be sourced for back-to-back adjacent windows") — `implementation/services/calculations.py:204` (pool filter), `:225` (half-open overlap).
- **§3.8** — revise — Cross-rental source path: dropped the unenforced "when the in-house candidate set is empty" precondition; pinned that sourcing with `use_cross_rental` creates the reservation in `DRAFT` (no in-house unit, no quote/hold yet), opens a `CrossRentalRequest` in `REQUESTED`, and leaves the rider line `REQUESTED` — `implementation/routes/rider_lines.py:135-158`, `implementation/services/domain.py:205-231`.
- **§3.8** — revise — Fulfillment now also pins: provisional quote computed at fulfillment from the vendor's daily rate; rider line moves `REQUESTED`→`SOURCED` with `fulfilled_by_reservation_id` set and the stop's `rider_revision` advancing — `implementation/routes/vendors.py:223-247`.
- **§3.9** — revise — DRAFT-tour cancellation cascade now covers reservations in `DRAFT` **or** `SOURCED`, each `SOURCED` one released with standard compensation (unit `RESERVED`→`AVAILABLE`, `active_reservation_id` cleared, hold credited back) — `implementation/routes/tours.py:164-168`.
- **§4 table** — revise — `/rider-lines/{id}/source` row description updated so it no longer claims a cross-rental source creates a SOURCED reservation — matches `rider_lines.py:146-158`.

**Step-7 items intentionally not turned into edits:** the test_05 waive/risk-recompute deletion (PRD §3.1 already pins exactly two triggers and the impl's waive path does not recompute — `damage_claims.py:123-132` vs `:77`,`:151`), the fixture reorder (pure fixture bug; §3.9's settle-time-risk rule already verbatim), the api_client retry hardening, the test_06 import fix, and the start.sh argv change (all infra, no PRD-visible behavior).

**Per-edit pre-edit search log:**
1. **§3.3 candidate pool** — (a) subject: unit eligibility in candidate selection. (b) enumerated: `gear_availability_window` (calculations.py:179-239) and all four callsites (rider_lines.py:161 source, :198 propose-substitution, :242 approve-substitution, :316 mark-shorted), plus the per-unit availability read (gear.py:168-188, no pool filter). (c) Wording widened from "units already in RESERVED stay in the pool" to "a unit already committed to another reservation stays in the pool" because the substitution/shorting callsites admit OUT_ON_RENTAL/IN_TRANSIT units too; retire's reservation-reference set (gear.py:159-161) confirmed disjoint from the conflict set, so no wording collision.
2. **§3.8 source path** — (a) subject: what sourcing with `use_cross_rental` does. (b) enumerated: rider_lines.py:135-158, domain.py:205-231, vendors.py:98-128 (direct create), :203-250 (fulfill), dispatch cross-rental skip (reservations.py:66-72), §2.11 gate order, tests test_02:134 and the five vendor-rep tests. (c) Removed the empty-pool precondition entirely rather than moving it, because the impl enforces it on neither entry path; kept the "could not be sourced in-house" phrase only on the direct-open sentence to avoid re-scoping it.
3. **§3.8 fulfillment** — (a) subject: fulfillment side effects. (b) enumerated: vendors.py:203-250 (quote, hold, DRAFT→SOURCED, line→SOURCED, rider_revision), §3.3 quote rule (vendor-rate base), §3.2 rider_revision rule. (c) None beyond insertion; phrased as additions to the existing sentence.
4. **§3.9 DRAFT-cancel cascade** — (a) subject: reservation set cancelled on DRAFT-tour cancel. (b) enumerated: tours.py:155-171 (DRAFT branch), :181-191 (ACTIVE branch, gate-flagged release), stops.py:176-183 (stop cascade, already DRAFT+SOURCED per §3.2), rider_lines.py:342-347 (line cancel), reservations.py:195-205 (reservation cancel), rider_lines.py:237-240 (substitution swap), domain.py:234-267 (release_reservation). (c) Copied the ACTIVE path's existing "standard compensation" phrasing so both sentences describe `release_reservation` identically; maintenance-gate re-run left pinned to the ACTIVE path only, matching the `run_maintenance_gate` flag.

## Step 9: Complete PRD — 2026-08-12T22:06:00.000Z

Produced `/home/ubuntu/github/CodingPRD/tasks/task_1294_backline_instrument_rental_tours/workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md` (the latest PRD; `PRD.md` left untouched).

## Size
- Source: `PRD_FINALIZED.md` — 372 lines / 59,093 chars. `PRD_COMPLETED.md` — 372 lines / 65,231 chars. Char delta: **+6,138**, line count unchanged (all edits are in-paragraph inserts/revisions; no new sections).

## Counts
- **Ambiguity-pins: 15** (PRD silent → pinned impl behavior)
- **Mismatch-revisions: 5** (PRD described different behavior → revised to impl)

## Changes (one bullet each)

Ambiguity-pins:
- §2.1 — insert — ambiguity — pinned vendor-rep confinement mechanics: ownership 422 on accept/reject/fulfill, list filtered to own vendor, single-fetch not ownership-restricted — `implementation/routes/vendors.py:139-200`
- §2.3 — insert — ambiguity — pinned pagination validation (non-integer/out-of-range → 400), `created_at`-ascending ties broken on `id`, `has_more` = `offset`+`limit` < `total_count` — `implementation/util.py:143-171,196-198`
- §2.4 — insert — ambiguity — pinned `version` starts at 1; all server timestamps (envelope + `created_at`/`updated_at`) come from the logical clock — `implementation/util.py:178-186`, `implementation/response.py:14-24`, `implementation/db.py:43-48`
- §2.5 — insert — ambiguity — pinned tours/stops/shipments echo date strings as supplied (`ship_date` never parsed); reservation dates normalized to UTC-midnight ISO — `implementation/routes/tours.py:38-39`, `implementation/routes/stops.py:48-49`, `implementation/routes/shipments.py:70`, `implementation/services/domain.py:168-169`
- §2.7 — insert — ambiguity — pinned `deposit_held_cents` zeroed on the reservation after any hold release — `implementation/services/domain.py:267`, `implementation/routes/reservations.py:189`
- §3.1 — insert — ambiguity — pinned top-up `amount_cents` is a required integer with no sign constraint (negatives reduce balance); PATCH naming neither field doesn't bump version; `risk_score` starts at 0 — `implementation/routes/artists.py:28,40-43,76-85`
- §3.2 — insert — ambiguity — pinned tour-create errors: unknown `artist_id` → 404, `end_date` < `start_date` → `ERR_INVALID_WINDOW` 422 — `implementation/routes/tours.py:24,31-32`
- §3.2 — insert — ambiguity — pinned `stop_count` counts cancelled stops and stop cancellation touches neither `stop_count` nor tour `version` — `implementation/routes/stops.py:55,163-186`
- §3.2 — insert — ambiguity — pinned rider-line create: unknown `gear_model_id`/`substitution_of_line_id` → 404; `rider_revision` starts at 0 — `implementation/routes/rider_lines.py:31,38-39`, `implementation/routes/stops.py:51`
- §3.2 — insert — ambiguity — pinned activation precondition order (DRAFT → OCC presence/match → PLANNED-stop → deposit → insurance), and that activating while a quote-less DRAFT cross-rental reservation exists fails 400 with the tour left ACTIVE (status flip precedes the recompute, which crashes on the null quote) — `implementation/routes/tours.py:80-105`, `implementation/services/domain.py:323-330`, `implementation/app.py:39-43`
- §3.3 — insert — ambiguity — pinned null `active_reservation_id` at unit birth; availability read requires both date params (400) and is purely conflict-based (status/condition not consulted); reservation field shape (`origin/dest_city_code`, window dates, null `settled_fee_cents`, `is_cross_rental`); source returns the reservation with 200 on both paths — `implementation/routes/gear.py:102,173-191`, `implementation/services/domain.py:161-179`, `implementation/routes/rider_lines.py:158,179`
- §3.4 — insert — ambiguity — pinned propose-substitution: both fields required, unknown substitute → 404, availability probe runs over the linked reservation's existing window and the stop's city — `implementation/routes/rider_lines.py:191-203`
- §3.4 — insert — ambiguity — pinned mark-shorted: probe window is the stop's single `venue_date` day; precondition violation → `ERR_INVALID_STATE` 409 — `implementation/routes/rider_lines.py:314-321`
- §3.5 — insert — ambiguity — pinned leg creation consults only tour existence (status ignored); booking accepted in any leg status with `weight_kg`/`labor_minutes` required; case-adequacy ladder `SMALL<MEDIUM<LARGE<TRUNK` (HEAVY≥LARGE, OVERSIZE=TRUNK); a case named for a non-requiring unit is recorded but never validated or flipped to ASSIGNED — `implementation/routes/shipments.py:18-25,36-47,57,106-120,174-188`
- §3.6 — insert — ambiguity — pinned staging's delivered leg must belong to the same tour; load-out stamps check-in from the logical clock; direct check-in requires `checked_in_at`; gate tie → `SCHEDULED_CYCLE`; forced routing clears `active_reservation_id` without accruing days; units in other statuses left untouched while the reservation lands RETURNED — `implementation/routes/stops.py:96-99,139`, `implementation/routes/reservations.py:98-101`, `implementation/services/calculations.py:122-133`, `implementation/services/domain.py:290-316`
- §3.7 — insert — ambiguity — pinned `repair_estimate_cents` required whenever `damage_present` is true (even TOTAL_LOSS); claim carries `gear_unit_id` and an `assessed_at_dt` field (null until assessment, then logical-clock stamped) — `implementation/routes/reservations.py:117-134`, `implementation/routes/damage_claims.py:55`
- §3.8 — insert — ambiguity — pinned source-path vendor fields both required (unknown vendor → 404); direct create performs no reservation-state check; commission uses the vendor's `commission_bps` current at settle time; premature cross-rental settle → 409; cancelling a request (directly or via suspension) leaves the linked reservation untouched — `implementation/routes/rider_lines.py:136-145`, `implementation/routes/vendors.py:98-128,253-281`

Mismatch-revisions:
- §2.10 + §3.2 — revise — mismatch — replaced "every rider-line mutation advances `rider_revision`" with the impl's exact set: +1 on create/source/cross-rental-fulfill/propose/reject, **+2 on approve** (reservation-create bump + line bump), none on mark-fulfilled/mark-shorted/cancel/cascades — `implementation/services/domain.py:198-201`, `implementation/routes/rider_lines.py:217-350` (fulfill/short/cancel lack `_bump_stop_revision`), `implementation/routes/vendors.py:244-247`
- §2.11 — revise — mismatch — softened gate-16 "deliberately last" and the "availability before window sanity" example: handlers read the body only after existence/state gates, and sourcing's start-before-end window sanity fires immediately after parsing, before candidate selection — `implementation/routes/rider_lines.py:106-126`
- §3.7 — revise — mismatch — quarantine source states are `OUT_ON_RENTAL`, `IN_TRANSIT`, **or `AVAILABLE`** (PRD named only the first two) — `implementation/routes/reservations.py:139`
- §3.8 — revise — mismatch — replaced "cross-rental never waives the deposit" with the tiered rule applied including its `deposit_waived` clause (a waived artist's cross-rental hold is zero), plus the 402 headroom failure at fulfillment — `implementation/routes/vendors.py:219-222`, `implementation/services/calculations.py:90-98`
- §3.4 — revise — mismatch — approval rewrites the line's `gear_model_id` to the substitute (settlement prices off it), and a create-half failure at approval (`ERR_GEAR_UNAVAILABLE`/`ERR_DEPOSIT_INSUFFICIENT`) leaves the old reservation's cancellation and compensation in effect with the line still `SUBSTITUTION_PENDING` — `implementation/routes/rider_lines.py:237-265`

All endpoint paths, RBAC roles, state machines, formulas (quote/cartage/insurance/deposit tiers/late fee/commission/risk score), and error catalogue entries were cross-checked and already matched; those needed no change.
