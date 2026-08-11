# Worklog — task_0947_piano_tuning_moving_restoration

Scenario (verbatim): `947. Piano Tuning, Moving & Restoration: client & instrument profile, tuning-cycle reminder & appointment, service (tune/regulate/voice/rebuild) & quote, specialized move & climate, deposit & milestone, technician & route, warranty, showroom/consignment linkage`

Difficulty: **beyond-Expert** (user: "generate task hard than expert level!")

## Step 1: Create task directory — 2026-08-09T10:27:43.000Z

Created `tasks/task_0947_piano_tuning_moving_restoration/workspace/`. Index 0947 = max(0946)+1.

## Step 3: Copy INSTRUCTION.md — 2026-08-09T10:27:43.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0947_piano_tuning_moving_restoration/workspace/INSTRUCTION.md` (done early, no dependency on Step 2).

## Step 2: Generate scaffold — 2026-08-09T11:24:00.000Z

All three scaffold artifacts are written and pass every gate.

## Files
- `SCAFFOLD.yaml` (4675 lines)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1471 lines)
- `SCAFFOLD_CORNER_DESIGN.yaml` (3123 lines)

## Scale
| dimension | value |
|---|---|
| entities | 18 |
| endpoints | 85 |
| error codes | 50 |
| state-machine axes | 16 — **all non-linear** (9 cyclic, 7 branching), incl. 2 parallel-axis pairs (Instrument `condition_status`×`custody_status`, Appointment `scheduling_status`×`fulfillment_status`) |
| calculations | 31, of which **11 dual-variant** |
| validation ladder | **60 numbered rungs**, 3 explicitly `mutate_then_reject` with stated precedence resolution |
| OCC rules | 5 (parents: Instrument ×2, RouteDay, PartsLot, Warranty) |
| conservation invariants | 6 (parts units, route minutes, client ledger, consignment proceeds, contract value, deposit disposition) |
| max cascade depth | **5** (cascade A unauthorized-move, cascade B rebuild-supersedes; cascade C at 4) |
| declared constants | **148, 0 undeclared** |
| §1.8 instances | 18 (9 rule_ids × 2) |
| §1.9 instances | 68 across all 9 guide sections (64 live + 4 `excluded_because` stubs); 0 name collisions with §1.8 |
| roles | 6, `segregation_of_duties` model with two independent SoD rungs |

## Lint verdict (verbatim)
```
  §1.5 endpoints declared:    85
  §1.1 entities declared:     18
  §1.8 instances scanned:     18
  §1.9 instances scanned:     64
  Calls scanned (§1.8+§1.9):  768
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Self-repairs (audits B–G)

**B — YAML lint (all three `safe_load` clean).** Two structural offenders fixed: (1) PyYAML rejects a `?`-suffixed plain scalar immediately before `]` in a flow sequence — quoted every optional field in 38 `input: [...]` lists; (2) `$.data[0].id` unquoted inside a flow mapping — quoted all 43 `captures:` JSONPaths.

**C — constant sweep.** 148 declared constants, **0 undeclared**. 7 residual ALL-CAPS tokens, all exempt: `ACTION_PREP`/`ACTION_REGULATION`/`FINAL_REGULATION`/`FINAL_VOICING`/`HAMMER_PREP` are milestone label string literals declared inline in `milestone_waterfall`; `ROUND_HALF_UP`/`HALF_UP` is the rounding mode, declared as `MONEY_ROUNDING`.

**D — reachability audit (7 repairs).**
1. **Sub-resource reverse-reachability broke on parameter naming** — lint check (f) matches the literal `{id}` segment; renamed all 243 path parameters to `{id}`.
2. **`ERR_MILESTONE_SEQUENCE` was dead** — milestone *i* only became READY after *i−1* was ACCEPTED, so rung 23 always pre-empted rung 54. Changed `ServiceOrder.start` to ready **all** milestones at once; ordering is now enforced solely at rung 54.
3. **Rung 37 was shadowed by rung 22** (both `ERR_INVALID_CUSTODY_STATE` on REBUILD start) — dropped the REBUILD clause from rung 22.
4. **Rung 25 was unreachable** ("appointment start requires DISPATCHED route day" is implied by the EN_ROUTE edge) — repurposed to two reachable cross-entity gates (confirm-while-dispatched, accept-while-not-IN_PROGRESS).
5. **`ServiceOrder.ON_HOLD` had a circular producer** — restricted its trigger to the appointment NO_SHOW, its only real path.
6. **SoD rungs 38/39 compared a possibly-null `X-User-ID`** for opaque roles — rung 1 now requires `X-User-ID` from any role on the four SoD endpoints.
7. **`LOYALTY_TIER_1` was arithmetically dead** (max non-rebuild subtotal 159 750 < 200 000; min rebuild subtotal 1 189 000 > 500 000). Retuned to `LOYALTY_TIER_1_MIN_CENTS: 119250` and `LOYALTY_TIER_2_MIN_CENTS: 1450000`, which also makes **both** tier boundaries hit *exactly* by real configurations (REGULATE/GRAND/ZONE_B = 119 250; REBUILD/UPRIGHT/retail = 1 450 000).

Additionally, `ERR_TECHNICIAN_ZONE_MISMATCH` would have killed the 55-minute cross-zone travel branch, so the rung was widened to allow an out-of-zone address for an in-zone client — both the error and the branch are now reachable.

**Ledger model repair (found while checking cascade A arithmetic).** The original "flip the original to REVERSED *and* post a negating REVERSAL" double-counted the reversal. Ledger is now strictly append-only: `LedgerEntry.status` was removed, the balance is the plain sum over all rows, and a reversal is a `REVERSAL` row carrying the negation with `reverses_entry_id` set. The forward row is never edited.

**E — instance-verb check.** One defect: `warranty_claim_prorated_credit_vs_free_reservice` cited `state_machines.WarrantyClaim.SUBMITTED_to_UNDER_REVIEW` as grounds but never performs a review — replaced with `entities.WarrantyClaim.fields.elapsed_fraction`. All other 17 §1.8 instances exercise every transition they cite.

**F — unique-derivability.** One §1.9 stub (`error_parts_insufficient_below_partial_floor`) cited a §1.8 instance that does not assert that error — converted to a live instance with its own chain. Every expected value in both design files derives from constants/formulas that live in `SCAFFOLD.yaml`.

**G — worked-example arithmetic.** All 38 numeric expected values recomputed by code; **0 failures**. One hand-arithmetic slip caught and fixed: a concert-grand crane move was stated as 357 000 but is 354 000. Day arithmetic verified against real calendars (2026 is non-leap): `2026-01-15 + 136d = 2026-05-31`, `+122d = 2026-05-17`, `+30d = 2026-02-14`, `2026-05-01 + 180d = 2026-10-28`.

## Notable seams
The 1-cent per-line-vs-sum rounding divergence is *provable* (36 604 vs 36 603, engineered via the odd 9 500 pitch-raise base). Move pricing is non-monotone on two independent axes — 4 stair flights (25 000) cost less than 3 (27 000), and 151 miles (52 000) less than 150 (63 000). The loyalty tier is keyed on `subtotal`, not `total`, with the order pinned to defuse the circularity. The overdue-recall tier bumps the pitch tier, so the same measurement produces a different service composition, duration and quote line count.

**Orchestrator independent verification:** all three files `yaml.safe_load` clean; top-level keys present; endpoints=85, entities=18, errors=50, calculations=31, state_machines=16 confirmed by parse. Independent ALL_CAPS sweep: 148 declared constant keys, 4 residual suspicious tokens (`CANCELLATION_FEE`, `DISPATCHED_TIER`, `LAPSED_TIER`, `LEAD_TIME_TIER`) — all confirmed enum members in `constraints:` lists, not constants. 0 undeclared.

## Step 4: Generate PRD — 2026-08-09T11:38:00.000Z

`workspace/PRD.md` — **552 lines, 16,678 words**. §1 Introduction (3 paras) → §2 with 12 subsections (2.1 roles/identity, 2.2 verbatim envelope, 2.3 pagination, 2.4 identity/versioning, 2.5 logical clock, 2.6 rounding, 2.7 OCC, 2.8 the 60-rung ladder, 2.9 mutate-then-reject, 2.10 invariants, 2.11 cascades, 2.12 ledger) → §3 with 10 domain subsections → §4 85-row endpoint table → §5 50-row error table. Neither design yaml was opened.

### Zero-Silence gate — residual counts

| Category | Required | Covered | Residual |
|---|---|---|---|
| Endpoints | 85 | 85 | **0** |
| Error codes | 50 | 50 | **0** |
| Declared constants (value literally in prose) | 148 | 148 | **0** |
| Calculations | 31 | 31 | **0** |
| State-machine transitions (16 axes) | 95 | 95 | **0** |
| Ladder rungs (ascending priority order) | 60 | 60 | **0** |
| Conservation invariants | 6 | 6 | **0** |
| OCC rules | 5 | 5 | **0** |
| Cascade hops (A=5, B=5, C=4) + non-firing conditions | 14 | 14 | **0** |

`MONEY_ROUNDING` is a prose string, not a number; rendered as the rounding-discipline paragraph in §2.6.

### Hard contracts
Field coverage: entity fields 155/155, endpoint inputs 90/90, path_params 1/1, state enum values 57/57, entity enum members 121/121 — PASS.
Rule coverage: 60/60 rungs in order, 5/5 OCC, 95/95 transitions, 31/31 calcs, 60/60 conditions matchable to error_id, 85/85 endpoint side_effects, 155/155 fields reconstructible, 21/21 sibling-branch groups equal density — PASS.
Path purity (§3): 1086 backtick tokens scanned, 0 leading-`/`, 0 bare HTTP methods, 0 method+path — PASS.
§2.2 diffs byte-identical against `section-2.2-response-structure.md`.

### Frictions carried forward (un-prejudged, each flagged in-document)
1. **§2.8, closing note** — rungs 34 and 52 both raise `ERR_TECH_CERT_INSUFFICIENT` on a route-day dispatch; one pre-commit, the other mutate-then-reject. Which governs is not settled.
2. **§2.10, closing note** — cancellation and Cascade-B refunds specified as `deposit_held − deposit_applied`, ignoring any `deposit_forfeited_cents` already booked; does not reconcile with the deposit-disposition identity.
3. **§3.1, closing note** — `recorded_at_utc` "must not be after the logical clock" has no error code anywhere in the ladder.
4. **§3.2, closing note** — the `AT_CLIENT_SITE → IN_TRANSIT` edge advances a quoted move job `DISPATCHED → IN_TRANSIT`; the `IN_SHOP → IN_TRANSIT` edge states only the unauthorized branch.
5. **§3.4, closing note** — the lapse sweep voids only `ACTIVE` warranties, while Cascade A voids `ACTIVE` **or** `TRANSFERRED`.
6. **§3.6, mid-section note** — milestone-accept credit precondition omits `deposit_refunded_cents`/`deposit_forfeited_cents` that rung 60 subtracts; and the sequence-1 release gate is stated two incompatible ways (deposit held vs. non-negative balance).
7. **§3.6, closing note** — `OPEN → DEPLETED` said to fire on "any allocation or consumption that drives `on_hand_qty` to 0", yet consumption is defined as leaving `on_hand_qty` unchanged.
8. **§3.7, closing note (two)** — the cancel edge posts the whole fee as a ledger row while the fee calculation charges the deposit first and posts only the residual; and `same_address_chained` is decided by `created_at` ordering, which a rescheduled stop carries over from its original day.

Not treated as a friction because the ladder settles it: rung 44 (climate) precedes rung 55 (claim cap), so a third claim filed at an out-of-band location voids the warranty and answers `ERR_CLIMATE_OUT_OF_BAND` rather than `ERR_ATTEMPT_LIMIT_EXCEEDED` — derivable from the stated order and written that way.

## Step 5: Generate unit tests — 2026-08-09T12:10:00.000Z

**`test_helpers/`** (2,363 lines): `__init__.py` 40 · `types.py` 364 · `api_client.py` 360 (one method per endpoint, all 85) · `api_errors.py` 114 (all 51 error ids + status map) · `assertions.py` 294 (incl. `assert_same_instant`, `assert_date_equals`, and all six conservation-invariant checkers) · `factories.py` 176 · `constants.py` 202 · `test_users.py` 73 · `fixtures.py` 740 (5 tiers, 14 composites)

**`test_suite/`** (3,550 lines): `conftest.py` 41 · `test_01_clients_addresses_and_climate.py` 254 · `test_02_instruments_pitch_and_recalls.py` 408 · `test_03_quote_pricing_and_lifecycle.py` 369 · `test_04_service_orders_and_milestones.py` 354 · `test_05_route_days_and_appointments.py` 589 · `test_06_specialized_moves.py` 308 · `test_07_warranties_claims_and_cascade_a.py` 363 · `test_08_consignment_and_showroom.py` 247 · `test_09_parts_and_inventory.py` 233 · `test_10_rebuild_cascade_and_custody_gates.py` 154 · `test_11_access_control_and_ladder_precedence.py` 230

### Coverage
- **§1.8 difficulty**: 18/18 instances translated, 0 skipped, **exactly 2 tests each = 36 tests**.
- **§1.9 corner**: 64/64 non-stub instances translated, 0 skipped, 1 test each = **64 tests**. The 4 `excluded_because:` stubs were verified to cross-reference real difficulty instances and were *not* translated.
- **Total `def test_`: 100.** No `skip`/`skipif`/`xfail` anywhere.

### Friction cross-check audit (8 flagged frictions)
- **CLEAN: 94 tests.**
- **AGREEMENT-BY-CONSTRUCTION: 4 tests**, each re-derived from PRD text + own test/fixture body, not asserted:
  - `test_the_voided_order_refunds_its_unapplied_deposit` (F2): fixture never cancels an appointment, so `deposit_forfeited_cents` is 0 — both formulas give 25000.
  - `test_milestone_acceptance_without_enough_credit_is_refused` (F6a): refunded and forfeited both 0 → both formulas give 4000; 0+4000 < 21000 rejects either way.
  - `test_consuming_an_allocation_moves_units_into_consumed` (F7): the lot reached `on_hand_qty` 0 at *reservation* time, so it is already `DEPLETED`; consumption cannot un-deplete it under either reading.
  - `test_cancelling_one_minute_inside_the_boundary_costs_fifteen_percent` (F8a): stop carries no `service_order_id`, and PRD pins "when there is no linked order, the whole fee posts as a `CANCELLATION_FEE` row".
- **DEPENDS → dropped: 2 assertions** (no test dropped):
  - `ERR_DEPOSIT_NOT_SETTLED` on the sequence-index-1 release (F6b) — unreachable in every possible scenario under one reading (`deposit_held` is copied from `deposit_required`, so held=0 ⟺ required=0). Error left untested; the instance's precedence claim survives via the milestone-2 case.
  - `Appointment.fulfillment_status == EN_ROUTE` on the partially-dispatched TUNE stop (F1). Test still asserts the 422, the offending stop still `PENDING`, day still `LOCKED`, `committed_minutes == 350`.

### Near-miss register (distance from the friction edge)
| Test | Friction | Distance |
|---|---|---|
| `test_milestone_sequence_rung_pre_empts_the_deposit_rung` | F6b | **0** — one added `release(milestone_1)` assertion flips it |
| `test_dispatch_stops_at_the_first_uncertified_stop` | F1 | **0** — one added assertion on `tune_stop` flips it |
| `test_resuming_the_order_unblocks_the_identical_milestone_release` | F8a | **1** — asserting `deposit_forfeited_cents` or the post-no-show balance would flip it |
| `test_the_voided_order_refunds_its_unapplied_deposit` | F2 | **2** — a prior appointment cancellation would split the two formulas |
| `test_above_reserve_sale_splits_the_proceeds_and_conserves_them` | F5 | **2** — adding a lapsed-recall sweep would hit "does lapse void a TRANSFERRED warranty" |
| `test_custody_transitions_leave_the_condition_axis_untouched` | F4 | **1** — switching to the shop-outbound `IN_SHOP → IN_TRANSIT` leg would hit the unsettled job-advance question |
| all climate-reading tests | F3 | **2** — every `recorded_at_utc` is at or before the clock |

### PRD gaps found (doc-generator feedback)
1. **`ERR_DEPOSIT_NOT_SETTLED` is untestable as written** — §3.6's own closing note offers a competing reading under which the error is unreachable for *every* input.
2. **Rung 34 vs rung 52 on dispatch (F1)** costs the suite §2.9's partial-dispatch observation.
3. §3.1's `recorded_at_utc` "must not be after the logical clock" has no error code (F3).

**Orchestrator verification:** 100 `def test_` confirmed; `Design:` tags 36 Difficulty + 64 Corner = 100; 0 `skip`/`xfail`.

## Step 6: Generate implementation — 2026-08-09T12:44:00.000Z

**Isolation containment applied.** Steps 5 and 6 missed their concurrent launch (Step 5 ran alone first), so before spawning Step 6 the orchestrator physically `mv`'d `test_helpers/` and `test_suite/` out of the task tree into the session scratchpad, and moved them back afterwards. Post-restore grep of `implementation/` for `test_suite|test_helpers|conftest` → 0 hits. The impl-gen subagent confirms it never searched for a test directory.

### Modules (4,635 lines total)
`app.py` 63 (early socket bind + `make_server(fd=…)`) · `api.py` 50 · `core.py` 648 (errors, envelope, logical clock, store, timestamps, ladder rungs 1–14) · `calc.py` 479 (148 constants + all 31 calculations) · `serialize.py` 169 · `services.py` 409 (ledger, climate, route minutes, cascades A/B/C, sweep) · `routes_admin.py` 34 · `routes_clients.py` 252 · `routes_instruments.py` 367 · `routes_scheduling.py` 687 · `routes_quotes.py` 244 · `routes_orders.py` 535 · `routes_moves.py` 218 · `routes_warranty.py` 213 · `routes_consignment.py` 216 · `_route_gate.py` 51 (dev tool, never imported by the app)

### Route-completeness gate (method+path pairs)
Subagent's `_route_gate.py`: **declared 85 / matched 85 / missing 0 / extra 1** (Flask's own `GET /static/…`).
**Orchestrator independent re-run** (own script, param names normalised to a placeholder since scaffold `{id}` vs impl `{cid}`/`{oid}` differ only in spelling): declared 85 / matched 85 / MISSING [] / EXTRA `[('GET','/static/{P}')]`. `__pycache__` removed afterwards.

### Timestamp three-case policy (HTTP-verified)
- (a) server identity stamps (`created_at`, `updated_at`, `meta.api_request_timestamp`): one producer `core.now_stamp()`, `YYYY-MM-DDTHH:MM:SS.mmmZ`, strictly monotonic (PRD §2.12 needs strictly increasing `created_at` across ledger rows written in one request while `posted_at_utc` is identical, so `created_at` cannot be the logical clock).
- (b) caller-supplied instants echoed byte-verbatim: `recorded_at_utc`, `scheduled_start_utc`, `scheduled_window_start_utc`, `scheduled_window_end_utc`, `current_utc`.
- (c) derived-from-caller stamps rendered in the source string's style: `issued_at`, `expires_at`, `notified_at`, `released_at`, `accepted_at`, `started_at`, `completed_at`, `posted_at_utc`.
HTTP-verified over three clock renderings (`…09:00:00Z` → `expires_at …Z`; `…09:00:00.500Z` → `.500Z`; `…09:00:00+00:00` → `+00:00`). No internal string comparison of timestamps — everything goes through `parse_iso()`.

### Enum routing — closed iff-list
Exactly 17 site-families route a bad member to `ERR_INVALID_ENUM`; no other field does: `client_type`, `home_zone_code`, `zone_code`, `instrument_class`, `usage_tier`, `service_type`, `to_condition_status`, `to_custody_status`, `to_status` (route-day + move-job, each against its own member list), `certification_level`, `part_type`, `decision`, `void_reason`, every field literally named `status` (body + query filter), the parallel-axis status filters (`custody_status`, `condition_status`, `scheduling_status`, `fulfillment_status`), `overdue_tier` filter, `zone_codes` array members.
**Named exclusion:** `entry_type` on `GET /ledger-entries` — enum-typed query filter, but the PRD's closed list names only status and overdue_tier filters; unknown value simply matches nothing. Also excluded: `expected_*_version`, ids, free text, numerics. **No vacuous members** — every listed member has ≥1 live request site.

### Boot robustness
`app.py` binds `0.0.0.0:$PORT` itself with `SO_REUSEADDR` and a bounded retry loop (20 s budget, 20 ms→250 ms backoff) **before importing Flask or any application module** — the bind is the third statement in the process, so the kill→bind window is a few ms. The bound socket is handed to `werkzeug.serving.make_server(..., fd=sock.fileno())`, so Werkzeug never binds and never reaches `sys.exit(1)`. **40 consecutive kill/restart cycles: 0 failures**, each boot showing 1 client after 1 create (no state carry-over).

### Grep audit (`sqlite|json.dump|pickle|/tmp/|datetime.now|utcnow|time.time()`)
3 hits, all justified; zero `sqlite`/`json.dump`/`pickle`/`/tmp/`/`utcnow`. `app.py:21,38` `time.time()` = bind-retry deadline (process lifecycle). `core.py:121` `datetime.now(timezone.utc)` = the sole wall-clock read, producing monotonic `created_at`/`updated_at` as PRD §2.12 requires; every *domain* temporal decision reads `CLOCK`. No `seed_*` function; store is plain dicts, empty at import.

### PRD ambiguity adjudications (17)
1. **Rung 21 vs the EXPIRED→SUPERSEDED edge** — chose "rung 21's terminal set for re-issue is {APPROVED, DECLINED, SUPERSEDED}", keeping the declared edge reachable. Verified: re-issue from EXPIRED → 201, `version_number` 2.
2. **`zone_codes` vs the closed enum list** — treated as the plural of a named enum field, so enum-routed.
3. **Rung 34 vs rung 52 on dispatch (F1)** — rung 34 is a no-op on route-day transitions (a RouteDay carries no `service_type`); rung 52 governs per-appointment, mutate-then-reject. Verified: first stop EN_ROUTE, second 422, day still LOCKED with unchanged `version`.
4. **Cancellation fee: edge clause vs calculation clause (F8a)** — chose the calculation (deposit absorbs first, residual posts); under the edge reading `deposit_forfeited_cents` would never be written by any operation.
5. **`IN_SHOP → IN_TRANSIT` with a quoted job (F4)** — the job advances `DISPATCHED → IN_TRANSIT` on both legs; rung 40 already requires DISPATCHED for any transition into IN_TRANSIT.
6. **DEPOSIT_REFUND with a zero amount** — appended unconditionally on order cancel and Cascade B hop 4 (hop 4 itself still gated on "had milestones in a cancellable status").
7. **Client `version` bump on balance recompute** — bumped only where PRD says so (credit adjustment, Cascade A hop 5, Cascade B hop 5, claim-denial hop 5); not on DEPOSIT_CHARGE / MILESTONE_CHARGE / CANCELLATION_FEE / CONSIGNMENT_PROCEEDS recomputes.
8. **Absent body on a no-input POST** — absent/empty = `{}`; present-but-malformed = `ERR_VALIDATION`. Otherwise `POST /quotes/{id}/issue` would be unreachable.
9. **Actor scope (rung 4) on list endpoints** — explicit client-scoping filter naming another client → 403 for both entity-backed roles; for `Client` only, results implicitly restricted to owned rows (scaffold roles says a Client's reads are "their own"; the Technician entry carries no such qualifier).
10. **Technician scope against a null owner** — a null `assigned_technician_id` is not an ownership violation.
11. **Move-job dispatch custody precondition** — rung 22's applies-to omits move jobs, so it answers `ERR_INVALID_STATE`, not `ERR_INVALID_CUSTODY_STATE`.
12. **`PATCH /clients` with `status` equal to the current value** — X→X is not a declared edge → `ERR_INVALID_STATE`.
13. **Warranty status on claim filing** — no rung gates it, so filing against a VOIDED/EXPIRED warranty is not blocked; rung 44 still voids only from ACTIVE/TRANSFERRED.
14. **Recall `days_overdue` at creation** — 0 / `ON_TIME` (declared defaults; the sweep is the declared refresher).
15. **`same_address_chained` on reschedule (F8b)** — literal formula `A2.created_at < this.created_at`; a rescheduled stop keeps its birth `created_at`.
16. **Location re-evaluation on clock set** — bumps `version` on a climate-reading append (scaffold states it), not on the clock-set re-run.
17. **Unnamed validation errors** — `email` without an at-sign, unparseable ISO instants, non-integer `amount_cents` → `ERR_VALIDATION`; negative `distance_miles_from_shop` → `ERR_VALUE_OUT_OF_RANGE`.

### Reachability audit — HYPOTHESES for downstream verification
- **All 50 error codes appear reachable.** 49 triggered in one scripted sweep; `ERR_TECH_CERT_INSUFFICIENT` confirmed separately at all three sites.
- **Rung 52 is only reachable via a post-booking downgrade** — book both stops with a MASTER → PATCH the technician to APPRENTICE → lock → dispatch. Without the PATCH the mutate-then-reject has no reachable input.
- **All three mutate-then-reject points confirmed** (rung 44 warranty VOIDED + version +1 + no claim row; rung 46 pitch fields written then 409; rung 52 first stop EN_ROUTE / day LOCKED / version unchanged).
- **All three cascades confirmed end to end** — A (5 hops, `-8666` reversal, balance restored), B (5 hops, `VOIDED_BY_REBUILD` → milestones CANCELLED → DEPOSIT_REFUND → balance), C (4 hops, SOLD → re-own → warranty TRANSFERRED with prorated `term_days` 80 → in-flight orders re-owned).
- **All 11 dual-variant calculations exercised**, incl. SINGLE_VISIT/SPLIT_VISIT (2400→2435), SAME_ADDRESS_CHAINED/DISTINCT_ADDRESS (buffer 5 vs 25, price 15600 vs 19500), LEAD_TIME_TIER/DISPATCHED_TIER (floor 15000), FREE_RESERVICE/PRORATED_CREDIT (fraction 0.5556, credit 8666), AT_OR_BELOW/ABOVE_RESERVE (45000 vs 25000 commission).
- **Arithmetic-feasibility notes.** `OVERDUE_BUMPED` needs `overdue_tier ∈ {OVERDUE_T2, LAPSED_TIER}`, written only by `POST /_ops/daily-sweep`. `ERR_DEPOSIT_NOT_SETTLED` needs a negative balance (DEPOSIT_CHARGE on an unfunded client, or a negative MANUAL_ADJUSTMENT). `ERR_PARTS_INSUFFICIENT` needs `on_hand < ceil(requested × 0.5)`; smallest refusing case requested 2 / on-hand 0.
- **Hypothesis — `ERR_ALREADY_TERMINAL` on the condition axis is unreachable.** `Instrument.condition_status` declares no terminal state, so rung 21 can never fire on `POST /instruments/{id}/condition-transitions`. The code is reachable on 12 other machines.
- **Hypothesis — `PartsLot` OPEN→DEPLETED on *consumption* is unreachable** (PRD §3.6 flags the tension): consumption leaves `on_hand_qty` untouched. Reachable only via allocation. Implemented as written.
- **Hypothesis — an `INSTITUTION` deposit of exactly 0 is reachable only through `total_cents == 0`**, which no pricing path produces.
- **Hypothesis — the `REBUILD_REQUIRED` condition edge is skipped from `NEEDS_ASSESSMENT`.** §3.2 declares the edge only from SERVICEABLE or NEEDS_REGULATION while §3.5 permits a REBUILD quote from every condition. A rebuild approved on a never-assessed instrument leaves `condition_status` at `NEEDS_ASSESSMENT`, and `REBUILD_REQUIRED → RESTORED` is then unreachable for it. Implemented literally; worth a downstream decision.
- **Hypothesis — `Appointment` `REQUESTED`/`RESCHEDULED` and `Milestone` `REJECTED` are never observable** — intra-request waypoints per PRD; every persisted read shows `SCHEDULED`/`READY`. Confirmed over HTTP for all three.

## Step 7: Run tests and iterate — 2026-08-09T13:20:00.000Z

## Result: 100/100 passing on 8 consecutive rounds

**Iterations: 2 sweeps** (1 fix).

| Sweep | WAVE | measured `/proc/loadavg` | foreign runners | per-round wall | outcome |
|---|---|---|---|---|---|
| 1 | 2 | 4.05 | 2 (task_0946, rounds 7–8) | 58.5–59.3 s | 99/100 ×8 |
| 2 | 4 | 0.99 | 0 | 60.4–60.6 s | **100/100 ×8** |

Sweep 1 sized at WAVE=2 per the "otherwise" rule; by sweep 2 the 0946 co-tenant had finished, so load<3 AND zero foreign runners → WAVE=4. No exit-143 / "could not be restarted" errors in either sweep, so no saturation to falsify.

### Tests deleted
None. The single failure was not a PRD-silence case.

### Fixes to `test_suite/`
- `test_02_instruments_pitch_and_recalls.py` → `test_overdue_recall_bumps_the_effective_pitch_tier`: pinned `validate_success(..., 201)` on `POST /instruments/{id}/pitch-assessments`; changed to `200`. **STEP 2 (test-vs-PRD consistency), not a deletion** — §4 says "Creating a new resource answers 201 Created…; every other successful operation answers 200 OK and returns the affected resource", and the PRD declares no `PitchAssessment` entity anywhere (§2.4's entity list names `ClimateReading` and `LedgerEntry` as its only two exceptions; §3.3 specifies the operation purely as writes onto the instrument). The affected resource is the instrument, which is exactly what the server returned. Deterministic in all 8 rounds; the test's substantive assertions (raw TIER_1 → effective TIER_2 bump, `planned_visit_count` 1) already passed. The impl returns 201 on exactly the 17 endpoints that mint a declared entity — a coherent §4 reading; leaving it alone was correct.

### Fixes to `test_helpers/` and `implementation/`
None.

### Verification audits

- **A. Per-test isolation is real — PROVEN.** Witnesses: `expired_quote_count == 1` (test_03:339) and `expired_consignment_count == 1` (test_08:201) — global daily-sweep counts. Falsification on `test_03` alone: `--isolation per-test-server` → **12/12 pass**; `--isolation none` (one shared server) → **10/12, 2 FAIL** — `test_daily_sweep_expires_an_issued_quote_past_its_window` fails `assert 2 == 1` (a second file's ISSUED quote leaked into the sweep) and `test_approving_a_quote_after_its_window_is_refused_as_expired` fails `Expected response_type 'error', got 'object'` (leaked clock). Scratch dir removed after the run.
- **B. All 8 rounds are the same suite — PASS.** 8/8 files parse; each `total=100, passed=100, failed=0, errors=0, skipped=0`, 100 individual rows, status set exactly `{'passed'}`. sha256 of the sorted test-name list = `9542b479951a3614…`, **identical across all 8** (and identical to sweep 1's, so nothing was collected differently).
- **C. Suite integrity — PASS.** `def test_` = 100, runner-collected = 100, `Design:` tags = 100. `skip`/`skipif`/`xfail` = **0**.
- **D. No persistence, no seeding — PASS.** Zero hits for `sqlite|json.dump|pickle|/tmp/`. Three time hits, all justified: `app.py:21,38` `time.time()` = the bounded pre-bind retry deadline in `_bind()` (socket only); `core.py:121` `datetime.now(timezone.utc)` inside `_mono_ms()` = the strictly-monotonic identity stamp per §2.4. Every temporal *decision* reads `CLOCK` (default `2026-05-01T00:00:00Z`, §2.5 verbatim); `posted_at_utc=CLOCK.stamp()` per §2.12. `Store.__init__` builds 18 empty dicts; no `seed_*`, no entity data at import.
- **E. Logs clean — PASS.** Each `round.N.log`: exactly **1** `Killed`, **0** `Traceback`, 127 lines.
- **F. Independent re-derivation of headline arithmetic — 3/3 AGREE.**
  1. *DEALER two-line TUNE, GRAND, ZONE_B* — TIER_2 → 2 lines; bases 19500×1.35=26325 and 9500×1.35=12825 → 39150; per-line ×0.82: 21586.5→**21587**, 10516.5→**10517**, sum 32104 → discount **7046** (sum-then-round would give 7047); +4500 ZONE_B → subtotal **36604** (≠36603); loyalty 0 (<119250); total **36604**. **AGREES.**
  2. *ABOVE_RESERVE split* (reserve 1 800 000, advance 1 363 000, sale 2 000 000) — recovered min→1 363 000; residual 637 000; excess 200 000; reserve portion 437 000; commission 0.15×437000=65 550 **plus** 0.50×200000=100 000, rounded independently = **165 550**; payout 637 000−165 550 = **471 450**; commission-last check 2 000 000−1 363 000−471 450 = **165 550**; conserves to 2 000 000. **AGREES.**
  3. *Tuning cycle + day arithmetic* — HOME 182 × 0.75 = 136.5 floored → 136, UPRIGHT +0, 30-floor last → **136 days**; 2026-01-15 + 136 across a **non-leap February** → **2026-05-31**; clock 2026-07-05 → **35 days overdue** → **OVERDUE_T2**; deviation −10.0 → raw TIER_1, bumped → effective **TIER_2**, `planned_visit_count` **1**. **AGREES.**

### Hand-off hypotheses (6 impl-gen + 2 test-gen)

1. `ERR_ALREADY_TERMINAL` unreachable on the condition axis — **CONFIRMED-BY-CODE.** `condition_transition` (`routes_instruments.py:263-289`) makes no `not_terminal()` call and no `CONDITION_TERMINAL` tuple exists; §3.2 "It has no terminal state". Minor correction: reachable on **14** other machines, not 12.
2. `PartsLot` `OPEN→DEPLETED` on consumption unreachable — **CONFIRMED-BY-CODE, for a stronger reason than stated.** `services.consume_allocation` *does* contain and execute `if lot["on_hand_qty"] == 0: lot["status"] = "DEPLETED"` — it just can never effect a transition, because `status == OPEN ⟹ on_hand_qty > 0` is an invariant (OPEN written only at creation where `on_hand = initial_qty ≥ 1`, and by `release_allocation` under `if on_hand > 0`; every path driving `on_hand` to 0 goes through the allocation branch that sets DEPLETED immediately). A no-op re-assignment on an already-DEPLETED lot, not dead code.
3. `INSTITUTION` deposit of exactly 0 requires `total_cents == 0` — **CONFIRMED in substance, REFUTED on the threshold.** `calc.deposit_required` returns `round_half_up(total × 0.10)` on NET_TERMS, which is 0 for any `total_cents ≤ 4`, not only 0. Unreachable either way: NET_TERMS is only entered for REGULATE/VOICE/REBUILD, whose cheapest path (VOICE, UPRIGHT, INSTITUTION) is 42000 → net 38640 → deposit 3864.
4. `REBUILD_REQUIRED → RESTORED` unreachable after a REBUILD quote approved from `NEEDS_ASSESSMENT` — **CONFIRMED-BY-CODE with a refinement.** `routes_quotes.py:181-184` gates the `REBUILD_REQUIRED` write on `condition_status ∈ {SERVICEABLE, NEEDS_REGULATION}` (§3.2 verbatim) while §3.5 permits a REBUILD quote from every condition; `services.advance_condition_on_complete` (`services.py:307-309`) then requires `current == "REBUILD_REQUIRED"`. Refinement: unreachable *along the quote-approval path only* — the technician-driven edge `NEEDS_ASSESSMENT → REBUILD_REQUIRED` (`routes_instruments.py:24`) is still an escape hatch, so not unreachable "for that instrument" absolutely.
5. `Appointment` `REQUESTED`/`RESCHEDULED` and `Milestone` `REJECTED` never observable — **CONFIRMED-BY-CODE.** These three strings appear *only* inside the enum tuples `core.py:378` and `core.py:386`; not one assignment anywhere. They exist solely so rung-6 status *filters* accept them.
6. Rung 52 only reachable via a post-booking technician downgrade — **REFUTED.** `cert_ok` has exactly three call sites: `routes_scheduling.py:182` (rung 52, dispatch), `routes_scheduling.py:327` (rung 34, booking), `routes_orders.py:54` (rung 34, order creation). **`reschedule_appointment` performs no certification check** — correctly, since rung 34 names only `POST /service-orders`, `POST /appointments` and `POST /route-days/{id}/status-transitions`. A second path exists with no downgrade: book onto a certified technician's day, reschedule onto an under-certified technician's OPEN day, lock, dispatch → rung 52 fires.
7. The 4 agreement-by-construction tests — **all 4 re-derived from PRD prose, all AGREE.** `test_the_voided_order_refunds_its_unapplied_deposit`: VOICE total 42000 → raw deposit 10500 < 25000 → FLAT_MINIMUM 25000 → balance 175000; Cascade B hop 4 refunds 25000−0 → 200000. ✓ `test_milestone_acceptance_without_enough_credit_is_refused`: milestones 21000+21000; accept #1 applies 21000 of the 25000 deposit, balance 0; accept #2 sees 0+4000 < 21000 → refused; after +17000, 21000 ≥ 21000 (rung 60 "at least") → applied 4000, single `MILESTONE_CHARGE −17000`. ✓ `test_consuming_an_allocation_moves_units_into_consumed`: reserve 2 of 2 → on_hand 0 → DEPLETED *at allocation*; consume → (0,0,2), still DEPLETED, conserves to 2 — genuinely agreement-by-construction and **benign** (the assertion cannot distinguish the two readings of §3.6's open point at line 327). ✓ `test_cancelling_one_minute_inside_the_boundary_costs_fifteen_percent`: clock at the §2.5 default → lead 71.9833 h ∈ [24, 72) → 15%; estimate 19500; fee **2925**; no linked order → whole fee posts, balance −2925. ✓
8. `ERR_DEPOSIT_NOT_SETTLED` untested because unreachable — **REFUTED on reachability, right call for the wrong reason.** `routes_orders.py:458-461` adopts the fiscal-rung reading (`sequence_index == 1` and `account_credit_cents < 0`), and the suite already *builds* that state: `test_unfunded_deposit_charge_leaves_the_client_in_debit` asserts the client sits at **−25000** with milestones READY. Releasing milestone 1 there would fire the error — one call away. Not testing it is nonetheless correct under STEP 1b: friction F6b (§3.6 line 315) leaves the release gate genuinely two-valued, so the error is unreachable under the other PRD-faithful reading and is not uniquely derivable.

### PRD gaps found but not acted on (documentation work items)
- **§4 status-code rule is under-determined for action sub-resources.** "Creating a new resource answers 201" leaves `POST /instruments/{id}/pitch-assessments` ambiguous because the path noun implies a resource the PRD never declares. This caused the only failure of the run.
- **Rung 34 vs reschedule.** Rung 34's operation list omits `POST /appointments/{id}/reschedule`, and §3.7 lists what reschedule recomputes without mentioning certification — so a stop can legally land on an under-certified technician's day and only surface at dispatch (rung 52). The un-signposted second producer of hypothesis 6.
- **§3.6's DEPLETED open point (line 327)** and **§3.6 line 315's two gate readings (F6b)** are both carried forward unresolved, and both are load-bearing for reachability (hypotheses 2 and 8).
- **§2.10's stated tension** between the cancellation-refund formula (`held − applied`) and the deposit-disposition identity that also counts `forfeited` remains unreconciled; no test exercises a cancellation-fee forfeit followed by an order cancellation, so the drift is unobserved rather than resolved.

**Orchestrator independent verification:** all 8 `results.N.json` parse with `total=100 passed=100 failed=0`, 100 individual rows each, status set exactly `{'passed'}`, sorted-name sha256 `9542b479951a` identical across all 8. `def test_` 100 == `Design:` tags 100; 0 skip/xfail. Each `round.N.log`: exactly 1 `Killed`, 0 `Traceback`.

## Step 8: Finalize PRD — 2026-08-09T13:32:00.000Z

### Counts
`PRD.md` 552 lines / 118,709 bytes → `PRD_FINALIZED.md` 552 lines / 124,053 bytes. Line delta **0.0%** (10 lines revised in place, none inserted or deleted); byte delta **+4.5%**.

### Changes
- **§4, opening paragraph** — revise — pins 201-vs-200 by *what the response body carries* (201 iff `data` holds a row this request minted): `credit-adjustments`→201 `LedgerEntry`, `reissue`→201 replacement quote, `service-orders/{id}/complete`→200 order despite minting a `Warranty`, `pitch-assessments`→**200** with the instrument (no `PitchAssessment` entity), the four `*-transitions` paths→200 — `routes_instruments.py:189`, `routes_quotes.py:243`, `routes_clients.py:127`, `routes_orders.py:238`.
- **§2.8 rung 6** — insert — a status filter accepts the whole declared value set of its axis, including never-persisted `REQUESTED`/`RESCHEDULED`/`REJECTED`, which are accepted and match nothing — `core.py:378,386`, `routes_scheduling.py:403-404`, `routes_orders.py:281`.
- **§2.8 open point after rung 60** — revise — rung 52 governs a dispatch; no separate day-level pre-commit certification check runs — `routes_scheduling.py:172-188`.
- **§2.10 "Deposit disposition"** — revise — identity qualified by the exception pinned below it — `routes_orders.py:264-265`.
- **§2.10 open point** — revise — the `held − applied` refund formula governs on both producers (subtracts neither `forfeited` nor `refunded`); the disposition sum therefore exceeds `held` by exactly the forfeited amount when a refund is booked after a forfeit — `routes_orders.py:264`, `services.py:189-190`.
- **§3.5 quote lifecycle** — insert — the REBUILD-approval condition write only fires from `SERVICEABLE`/`NEEDS_REGULATION`; from any other condition the axis is untouched while the quote still approves and Cascade B still fires; consequence for completion never reaching `RESTORED` — `routes_quotes.py:179-185`, `services.py:307-310`.
- **§3.6 acceptance** — insert — applied portion is floored at 0 (a negative unapplied deposit applies nothing, never claws back) — `routes_orders.py:495`.
- **§3.6 open point (two gate pairs)** — revise — the fiscal rung governs both: acceptance uses the four-term unapplied deposit; `sequence_index` 1 release consults only `account_credit_cents < 0`, never the order's deposit fields — `routes_orders.py:458-461`, `:489-493`, `services.py:400-403`.
- **§3.6 open point (lot depletion)** — revise — consumption never touches `on_hand_qty` so never effects `OPEN→DEPLETED`; reservation is the only producer, release the only path back; `DEPLETED` ⟺ `on_hand_qty == 0` — `services.py:248-269`, `routes_orders.py:361-365`.
- **§3.7 reschedule** — insert — no certification gate is re-run on the target day; a stop can legally land on an under-certified technician and only rung 52 catches it — `routes_scheduling.py:461-557` (no `cert_ok` call).

### Per-edit pre-edit search log (NO-NEW-MISMATCH rule)
1. **§4 status codes.** (a) HTTP status of every POST. (b) All 17 `ok(..., 201)` sites across 9 route modules plus every default-200 `ok(...)` return. (c) **Adjustment:** the first wording ("minting a persisted row … and nothing else") would have made `service-orders/{id}/complete` (mints a `Warranty`) and every ledger-appending action 201 — a new mismatch. Re-scoped to what the response body returns, naming the completion case explicitly.
2. **Rung 6 status filters.** (a) Filter enum membership. (b) All 22 `enum_q` call sites; confirmed `entry_type` on `/ledger-entries` is *not* enum-validated, matching rung 6's closed list. (c) None.
3. **Rung 34/52 dispatch.** (a) Where the certification gate runs. (b) All three `cert_ok` call sites; `route_day_transition` read in full. (c) Reworded so it does not declare rung 34's operation list wrong — says rung 34 "adds nothing ahead of" rung 52 on that operation.
4. **§2.10 identity + refund.** (a) The four deposit fields. (b) Every read/write of `deposit_held/applied/refunded/forfeited` (`routes_orders.py:79-81,264-265,497`, `services.py:189-190,402-403`, `routes_scheduling.py:261-265`). (c) Dropped "single exception" and re-anchored on "an order that books one of those two refunds", since Cascade B skips the refund when no milestone was cancellable.
5. **§3.5 REBUILD approval.** (a) Writers of `condition_status`. (b) `routes_quotes.py:181-184`, `services.advance_condition_on_complete:298-310`, `CONDITION_EDGES` at `routes_instruments.py:21-27`, `condition_transition:263-289`. (c) Added the "unless a technician drives `NEEDS_ASSESSMENT → REBUILD_REQUIRED`" escape hatch — the absolute claim would have been false.
6. **§3.6 applied floor.** (a) The applied-portion computation. (b) `routes_orders.py:489-499`, `services.order_unapplied_deposit`, `_fee_settlement` (forfeits accumulate off a base ignoring prior forfeits, so unapplied *can* go negative). (c) None.
7. **§3.6 two gate pairs.** (a) Release and accept fiscal gates. (b) `routes_orders.py:458-461`, `:486-496`; cross-checked rungs 59/60. (c) Added "No milestone at any other `sequence_index` is subject to that gate".
8. **§3.6 lot depletion.** (a) Writers of `parts_lot.status` / `on_hand_qty`. (b) `routes_orders.py:307-315,361-365`, `services.consume_allocation`, `services.release_allocation`; verified allocation from a 0-on-hand lot always fails the partial floor first, so `OPEN ⟺ on_hand > 0` holds on every path. (c) None.
9. **§3.7 reschedule.** (a) Gates re-run on reschedule. (b) `reschedule_appointment` read line-by-line (no `cert_ok`, no client-standing, no technician-standing check). (c) Phrased purely negatively about certification with rung 34's list as the reason, so nothing is implied about client/technician standing.
10. **§3.7 "It increments" referent** — mechanical follow-up to edit 9.

### Items deliberately not patched
- **(b) INSTITUTION deposit threshold** — REFUTED and already determined: §3.5 says "10 percent of `total_cents`, rounded half up, with no floor of any kind", which yields 0 for any `total_cents ≤ 4`. `calc.deposit_required` matches verbatim.
- **(f) the three never-assigned enum members** — partially patched (the filter-membership half, at rung 6). The "never persisted" half is already verbatim in §3.6 and §3.7; the implementation never assigning them even transiently is unobservable.
- **(g) rung 21 unreachable on condition-transitions** — already determined: §3.2 states the condition axis "has no terminal state". The implementation makes no choice here.

## Step 9: Complete PRD — 2026-08-09T13:50:00.000Z

**Source vs output:** `PRD_FINALIZED.md` 552 lines / 124,053 chars → `PRD_COMPLETED.md` 556 lines / 159,101 chars (**+4 lines, +35,048 chars**). Headings unchanged (no new sections); §4 and §5 table row counts unchanged (139). Only structural additions: two bolded clarifier paragraphs inside §2.8, matching that section's existing convention.

**61 lines touched — 48 ambiguity-pins, 13 mismatch-revisions.**

### Per-question tally
| Q1 field never read | Q2 projections | Q3 list order/filters | Q4 defaults | Q5 error/404 order | Q6 cascade legs | Q7 version ledger | Q8 timestamps | Q9 un-numbered rungs | Q10 money order |
|---|---|---|---|---|---|---|---|---|---|
| 9 | 4 | 12 | 6 | 4 | 8 | 11 | 3 | **21** | 3 |

**Sharpest finding:** Q9's un-numbered-precondition inventory — a 60-rung ladder that claims "the first error it reaches" while the code enforces eighteen further gates the ladder never numbers, two of which (`service_date`, `cycle_start_date`) are *format* checks deliberately sitting **after** their parent's existence rung, so a malformed date paired with an unknown parent answers 404 rather than 400.
**Runner-up:** the reschedule fee is priced off the **vacated** start time, not the requested one — a stop moved from next month to tomorrow is free while the reverse costs 7500 cents, and no test could see it because Step 7 never rescheduled across the 48-hour boundary in both directions.

### Changes (61)
- §2.1 — insert — ambiguity — actor-scope on *list* endpoints: an ownership filter naming another party is 403; a `Client` with no filter is silently narrowed and `total_count` narrows too; a `Technician` with no filter is not — `core.py:453`, `routes_orders.py:119`
- §2.4 — insert — ambiguity — the three timestamp-rendering rules (canonical `.mmmZ` identity stamps off the **host** clock; caller instants echoed byte-verbatim; business stamps rendered in the clock-setting string's style, no fractional digits by default); date fields plain `YYYY-MM-DD` — `core.py:1-27,128,223`
- §2.5 — revise — ambiguity — `to_iso8601` must parse (`ERR_VALIDATION`); clock may move backwards; `data` is a two-key non-resource; `current_utc` echoes byte-verbatim; clock re-run bumps **no** location version — `routes_admin.py:11`, `services.py:76`
- §2.7 — insert — ambiguity — version fields compared by plain integer equality, wrong JSON type → 412 not 400 — `routes_quotes.py:67`
- §2.8 — insert — ambiguity — **the un-numbered-precondition inventory**: 5 format checks at rung 5's slot, 2 format checks that sit *after* their parent resolves (`service_date`, `cycle_start_date`), and 11 un-numbered `ERR_INVALID_STATE` gates with their exact ladder positions — `routes_scheduling.py:98,174,321,494`, `routes_orders.py:167`, `routes_moves.py:162,173`, `routes_instruments.py:222,282`
- §2.8 — insert — mismatch — rung 21 does **not** reach `POST /quotes/{id}/reissue` (EXPIRED excluded) or `POST /warranty-claims` (no terminal gate at all); rung 6 admits `SHOWROOM_FLOOR`/`SOLD`/`NEEDS_VOICING`/`RESTORED` that fall to rung 23 — `routes_quotes.py:22,216`, `routes_warranty.py:91`
- §2.9 — insert — ambiguity — climate gate does not increment `claim_count`; voids the parent only if `ACTIVE`/`TRANSFERRED` but rejects regardless — `routes_warranty.py:103`
- §2.9 — insert — ambiguity — first-ever assessment always counts as a tier change (`pitch_raise_tier` starts null) — `routes_instruments.py:170`
- §2.10 — insert — ambiguity — route-day recompute always bumps `version` even on a no-change pass — `services.py:99`
- §2.10 — insert — ambiguity — **the client-version split**: bumped on credit-adjustment + Cascade A/B hop 5; not bumped on `DEPOSIT_CHARGE`, `MILESTONE_CHARGE`, cancel `DEPOSIT_REFUND`, `CANCELLATION_FEE`, `WARRANTY_CREDIT`, `CONSIGNMENT_PROCEEDS` — `services.py:33`, `routes_orders.py:110`
- §2.11 A/1 — insert — ambiguity — `unauthorized_move_flag` is never lowered again — `routes_instruments.py:242`
- §2.11 A/4 — revise — mismatch — the `REVERSAL` posts to the `client_id` **on the original credit row**, not the warranty's current owner — `services.py:143`
- §2.11 B/3 — insert — ambiguity — hop 3 also releases the order's `RESERVED`/`PARTIAL` allocations (unnamed leg) — `services.py:207`
- §2.11 B/4 — revise — ambiguity — `deposit_refunded_cents` is **set**, not incremented; the row fires on "a milestone was cancellable", not on a positive amount, so a 0-cent `DEPOSIT_REFUND` is real — `services.py:188`
- §2.11 C — insert — ambiguity — Cascade C bumps no `Client` row at all; buyer's balance untouched — `routes_consignment.py:193`
- §2.12 — revise — mismatch — FK map corrected: `CANCELLATION_FEE` carries `service_order_id` (or null) and `REVERSAL` carries **both** `reverses_entry_id` and `warranty_claim_id`; `memo` only ever set by credit-adjustment — `services.py:143`, `routes_scheduling.py:269`
- §2.12 — insert — ambiguity — **no operation ever appends two different `entry_type`s in one request**, so the eight-way precedence governs vacuously; multi-row requests are single-type, walked in cascade order — all `post_ledger` call sites
- §3.1 — insert — ambiguity — email at-sign → `ERR_VALIDATION`; every `PATCH /clients/{id}` bumps version even when empty; client list filters — `routes_clients.py:31,110`
- §3.1 — insert — ambiguity — close-over-in-flight-order → `ERR_INVALID_STATE`; a `status` restating the current value is not an edge — `routes_clients.py:92,101`
- §3.1 — insert — ambiguity — `amount_cents` must be a JSON integer (`ERR_VALIDATION`), unranged; zero adjustments still write and bump; `memo` null-by-default and never read — `routes_clients.py:121`
- §3.1 — insert — ambiguity — negative `distance_miles_from_shop` → `ERR_VALUE_OUT_OF_RANGE` though rung 7 omits the field — `routes_clients.py:144`
- §3.1 — insert — ambiguity — `address_key`/`client_id` immutable; update bumps version and does **not** re-run climate; location list filters + `Client` narrowing — `routes_clients.py:207`
- §3.1 — insert — ambiguity — `recorded_at_utc` byte-verbatim; `in_band` is read by nothing; readings list unfiltered — `routes_clients.py:230,243`
- §3.1 — insert — ambiguity — appending a reading bumps the location's version; the clock re-run does not — `routes_clients.py:238` vs `services.py:82`
- §3.1 open point — revise — ambiguity — future-dated and unparseable `recorded_at_utc` accepted and stored, then silently excluded from every window — `services.py:58`
- §3.2 — insert — ambiguity — creation defaults: `planned_visit_count` is **1** not null; pitch fields, interval and agreement id null; `last_tuning_date` unvalidated — `routes_instruments.py:67-77`
- §3.2 — insert — mismatch — `PATCH /instruments/{id}` is **not** covered by rung 17, so an edit may move an instrument onto another client's address — `routes_instruments.py:135`
- §3.2 — insert — ambiguity — instrument list order/filters and `Client` narrowing — `routes_instruments.py:84`
- §3.2 — insert — ambiguity — condition custody gate runs **before** the edge test; missing-pitch refusal is `ERR_INVALID_STATE` after the edge test; `note` stored nowhere — `routes_instruments.py:272-284`
- §3.2 — insert — ambiguity — in-flight-order gate on `IN_SHOP → IN_TRANSIT` is `ERR_INVALID_STATE` between rungs 23 and 40; exactly one instrument bump per custody edge; `SHOWROOM_FLOOR`/`SOLD` unrequestable — `routes_instruments.py:221,239`
- §3.2 open point — **revise — resolved** — quoting a job on the shop-outbound leg **does** advance it `DISPATCHED → IN_TRANSIT`, symmetrically with the client-site leg — `routes_instruments.py:246`
- §3.3 — insert — ambiguity — the bump reads the recall's **stored** `overdue_tier`, refreshed only by the sweep, so whether an assessment bumps depends on when the sweep last ran — `calc.py:159`
- §3.4 — insert — ambiguity — `cycle_start_date` ISO check after the instrument resolves; a new recall is always born `days_overdue` 0 / `ON_TIME`; recall list order/filters — `routes_instruments.py:302,318`
- §3.4 — insert — ambiguity — sweep walks each step in `created_at` order; `data` is the six-count object; a merely re-banded recall gets **no version bump and no `updated_at`**; `SCHEDULED` recalls can never lapse — `services.py:330-340`
- §3.4 open point — **revise — resolved** — the lapse step voids `ACTIVE` warranties only; a `TRANSFERRED` warranty survives its instrument's lapsed cycle — `services.py:342`
- §3.5 — insert — ambiguity — a never-assessed instrument's null `pitch_raise_tier` prices as one line and reads through duration/`service_minutes`/`estimated_price_cents` identically — `calc.py:207`
- §3.5 — insert — ambiguity — decline `reason` stored nowhere; declining is not gated on client standing — `routes_quotes.py:190`
- §3.5 — insert — ambiguity — reissue re-runs the service ladder but re-checks neither client standing nor the one-issued rule; terminal set excludes `EXPIRED`, `DRAFT` → `ERR_INVALID_STATE`; quote list order/filters — `routes_quotes.py:216-224`
- §3.6 — revise — ambiguity — the parts requirement is surfaced as a `parts_requirement` object on the serialized `REBUILD` order only, absent elsewhere, and no gate ever compares it to actual allocations — `serialize.py:135`
- §3.6 — insert — ambiguity — unassigned-order start → `ERR_INVALID_STATE` before the custody gate; neither cert nor client standing re-examined at start — `routes_orders.py:167`
- §3.6 — insert — ambiguity — a 0 residual writes no `MILESTONE_CHARGE`; acceptance bumps the order then the milestone — `routes_orders.py:500`
- §3.6 — insert — ambiguity — completion's condition advance and tuning stamp are mutually exclusive → instrument bumps **at most once**, and not at all for a `REBUILD` completed out of `IN_SHOP` — `services.py:298`
- §3.6 — insert — ambiguity — reject `reason` stored nowhere; rejection does not examine the order's status — `routes_orders.py:512`
- §3.6 — revise — ambiguity — order-cancel refund is **unconditional** (0-cent row when no deposit), `deposit_refunded_cents` set not added, children walked in sequence/created order, `reason` discarded — `routes_orders.py:252-268`
- §3.6 — insert — ambiguity — parts reservation gates on **neither** `service_type` nor order status; only consumption is gated — `routes_orders.py:330`
- §3.6 — insert — ambiguity — order list order/filters and scope; milestones sorted by `sequence_index` **before** filter and pagination — `routes_orders.py:286`
- §3.7 — insert — ambiguity — `zone_codes` shape errors; technician revision runs no state machine and always bumps; capacity/cert changes are not retroactive — `routes_scheduling.py:68`
- §3.7 — insert — ambiguity — `service_date` ISO check after the technician resolves; duplicate/past service dates allowed; route-day list order/filters — `routes_scheduling.py:98`
- §3.7 — insert — ambiguity — a linked recall moves only from `NOTIFIED` (silent no-op otherwise); neither `tuning_recall_id` nor `service_order_id` is checked for coherence with the stop — `routes_scheduling.py:374`
- §3.7 — insert — ambiguity — appointment list order/filters and `Client` narrowing — `routes_scheduling.py:399`
- §3.7 — insert — mismatch — completing a stop stamps `last_tuning_date` **only** when the linked recall was `SCHEDULED`; a no-show does **not** hand the recall back to `NOTIFIED` — `routes_scheduling.py:646,659`
- §3.7 — insert — mismatch — the reschedule fee reads the **old** `scheduled_start_utc`, not the new one; same-day reschedule subtracts its own block before the capacity test and bumps the day once; cap tested between rungs 50 and 57 — `routes_scheduling.py:522-533`
- §3.7 — insert — ambiguity — `cancellation_fee_cents` is never written by a reschedule; a reschedule leaves the linked recall standing; cancel `reason` discarded — `routes_scheduling.py:543`
- §3.7 open point 1 — **revise — resolved** — the deposit-first calculation governs; a fee fully absorbed writes **no** ledger row; balance recomputed only when the fee > 0; order bumped only when the forfeit > 0 — `routes_scheduling.py:253`
- §3.7 open point 2 — **revise — resolved** — on a reschedule only stops created strictly **earlier** than the moved stop chain; a stop moved onto a day of newer stops forfeits both the 5-minute buffer and the 20 % discount — `routes_scheduling.py:199,506`
- §3.8 — insert — ambiguity — window instants must parse (`ERR_VALIDATION`) before ids resolve, end≤start is rung 7; both stored byte-verbatim; crew lead not cert-checked at creation; rung 17 binds **both** endpoints — `routes_moves.py:34-52`
- §3.8 — insert — mismatch — the `DISPATCHED` custody gate answers `ERR_INVALID_STATE`, **not** `ERR_INVALID_CUSTODY_STATE`, which this operation never raises; missing crew lead → `ERR_INVALID_STATE`; `IN_TRANSIT`/`DELIVERED` unrequestable; `reason` discarded — `routes_moves.py:162-176`
- §3.9 — insert — mismatch — a manual void accepts **any** of the four `void_reason` members, not only `MANUAL` — `routes_warranty.py:64`
- §3.9 — insert — mismatch — claim filing applies **no** terminal gate: a claim may be filed against a `VOIDED` or `EXPIRED` warranty; the fraction uses re-based transfer figures — `routes_warranty.py:91`
- §3.9 — insert — ambiguity — the provisional credit posts to the warranty's current client without bumping its version; `elapsed_fraction` served as a 4-dp number; `credit_cents` 0 not null — `routes_warranty.py:128`
- §3.9 — insert — ambiguity — the segregation set is the **non-null** `released_by_user_id` values now standing, so a rejected release no longer bars its author — `routes_warranty.py:195`
- §3.9 — insert — ambiguity — a cascade denial leaves `adjudicated_by_user_id` null; claim and warranty list order/filters — `routes_warranty.py:25,136`
- §3.10 — insert — ambiguity — `reserve_price_cents`/`sale_price_cents` must be JSON integers; drafting is gated on neither custody nor a prior agreement — `routes_consignment.py:28,156`
- §3.10 — insert — ambiguity — activation's custody gate runs at rung 22 ahead of the edge test; `advanced_restoration_cents` is taken **once** and never recomputed — `routes_consignment.py:105,116`
- §3.10 — insert — ambiguity — withdrawal `reason` discarded; the instrument bumps once if either write fired and not at all otherwise; the link is cleared only when it still names *this* agreement; agreement list order/filters/scope — `services.py:380`
- §4 intro — insert — ambiguity — the two non-resource 200 responses; unknown path **and method mismatch** both answer 404 `ERR_RESOURCE_NOT_FOUND` — `api.py:36`
- §4 table — revise — mismatch — `GET /ledger-entries` has **no** status filter (the entity has no status), and `entry_type` is matched as a plain string, so an off-enum value yields an empty page rather than `ERR_INVALID_ENUM` — `routes_moves.py:197`

## Final integrity audit — 2026-08-09T13:52:00.000Z

- `workspace/` contains `PRD.md` (552) / `PRD_FINALIZED.md` (552) / `PRD_COMPLETED.md` (556), `implementation/`, `INSTRUCTION.md`, `sweep.sh`.
- `diff` of all `^#` headings, `PRD.md` vs `PRD_COMPLETED.md` → **identical** (no sections added or renamed across Steps 8+9).
- `find workspace/implementation -newer results.1.json` (excluding results/round/marker files, after clearing `__pycache__`) → **empty**: Steps 8 and 9 touched no implementation file, so the 8-round green sweep still describes the shipped code.
- `find test_suite test_helpers -newer results.1.json` → **empty**: the tests are exactly what passed.

Host note: sibling pipelines task_0944 / task_0945 / task_0946 are active concurrently (all mid-Step-2 at 10:27 UTC); loadavg 0.89 at launch. Sweeps will be sized against measured load.
