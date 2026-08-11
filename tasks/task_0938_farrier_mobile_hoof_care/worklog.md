# Worklog — task_0938_farrier_mobile_hoof_care

Scenario (verbatim): `938. Farrier & Mobile Hoof-Care: client/horse profile & 6–8-week cycle, route & appointment, service (trim/shoe/corrective) & pricing, recurring auto-schedule & reminder, product/shoe inventory, lameness/vet coordination, per-visit billing, no-show`

Difficulty: **beyond-Expert** (user request: "generate task hard than expert level!")

## Step 1: Create task directory — 2026-08-09T04:34:50.000Z

Created `tasks/task_0938_farrier_mobile_hoof_care/workspace/`. Index 0938 (highest existing was 0937).
Host pre-flight: load 0.57 on 8 cores, 0 orphan `app.py` / Flask processes.

## Step 2: Generate scaffold — 2026-08-09T05:36:00.000Z

All three scaffold artifacts are written and verified.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_0938_farrier_mobile_hoof_care/`): `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`. No sibling task was read.

### A — Incremental writes
Every file was built in bounded appends (preamble+constants → entities → state machines → gates/OCC/cascades/invariants → calculations → validations → endpoints ×2 → errors/roles; design files in 3 chunks each). No single oversized write; no truncation.

### B — YAML lint
`yaml.safe_load` succeeds on all three files. Two real offenders hit and fixed: `?` terminates a plain scalar inside a flow sequence (`input: [..., blackout_dates?]` → quoted), and `[` inside a flow mapping/sequence (`captures: { lf: $.data[0].id }`, `grounds: [errors[X], ...]` → quoted). `scaffold_lint.py` verdict, verbatim:

```
Coverage
  §1.5 endpoints declared:    86
  §1.1 entities declared:     19
  §1.8 instances scanned:     18
  §1.9 instances scanned:     65
  Calls scanned (§1.8+§1.9):  1069

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

### C — Undeclared-constant sweep
**64 declared constants, ZERO undeclared.** An automated sweep of all ALL_CAPS multi-word tokens across all three files (minus error ids, enum members, state names, gate/invariant ids) returns an empty set. Every mapping a validation depends on is stated in a `constant_mappings:` block rather than left to invention: service_type→units, →minutes, →rate-card price field, →required-SKU flag, →resulting shoeing state; barn zone→travel minutes and →trip-fee field; certification level→allowed service types; the `ceil(shoe_count / SHOES_PER_PAIR)` pair formula; round_half_up; week/day arithmetic; weekday derivation.

### D — Reachability audit (graph **and** arithmetic), with repairs
All 93 transitions, 53 ladder rungs and all 4 cascade chains have a concrete request sequence. Arithmetic checked by hand for the two capacity meters: units-only refusal is 16+16+16=48 > 44 while minutes sit at 345/480; minutes-only refusal is 8 zone-C stops (400) + one sedated 4×GLUE_ON horse (128) = 528 > 480 while units sit at 16/44. Both meters are independently violable — an earlier draft had every service-type unit/minute ratio above the cap ratio, which would have made `ERR_ROUTE_MINUTE_CAPACITY_EXCEEDED` unreachable.

Repairs made (design changed, no dead branch documented):
1. **Missing self-loops on `LimbState`** — a barefoot trim, the commonest farrier service, had no declared transition. Added `BAREFOOT→BAREFOOT` (TRIM), `SHOD_WITH_PAD→SHOD_WITH_PAD` / `GLUED→GLUED` (RESET), `SHOD→SHOD_WITH_PAD`, `GLUED→SHOD_WITH_PAD`.
2. **`MAX_CONSECUTIVE_RESETS` 2 → 1** so `ERR_RESET_LIMIT_REACHED` is reachable in a two-visit chain instead of three.
3. **`replenishment_flag` default false → true** and its axis initial state `CLEAR → FLAGGED`: a freshly minted bucket has 0 available pairs and `0 <= REORDER_POINT_PAIRS`, so the declared default contradicted its own calculation.
4. **Enum-closure dead ends removed** — `Barn.status`, `Client.account_status`, `ShoeSku.status`, and RateCard's `DISCARDED` had no producing endpoint or transition.
5. **`POST /appointments/{id}/service-lines` made atomic over a `lines` array** — one-line-per-call forced a fresh appointment version per limb, making the OCC field unusable in a writable setup chain.
6. **`opening_completed_visit_count?` added to `POST /clients`** — `LOYALTY_THRESHOLD_VISITS` (12) is not reachable by completing twelve real visits.
7. **RESET/pad contradiction fixed** — the resulting-state map said RESET→SHOD while the machine declared RESET self-loops; RESET is now `UNCHANGED` and `with_pad` is rejected for TRIM, RESET and GLUE_ON.
8. **Rung 52 split** — `ERR_NO_EFFECTIVE_RATE_CARD` had been folded into the shop-stock rung's check text under the wrong `error_id`; it is now rung 53, last, and reachable (TRIM-only lines pass every earlier rung with no rate card present).
9. **Snap-forward reachability** — cycles are whole weeks, so `raw_due` always shares the completion date's weekday. Pinned the reachable path (completion stamps the *logical clock* date, which need not equal `route_date`) and covered both the offset-1 hit and the beyond-cap miss.

### E — Cross-file consistency
Automated: **0 unresolved `grounds` references** across all 88 instances (resolver checks entities/fields, calculations, `state_machines.<Entity>.<FROM>_to_<TO>` against actual transition pairs, `validations[priority=N]`, `errors[...]`, `constants.*`, `concurrency_rules[...]`, `cascades.*`, `conservation_invariants.*`). **0 duplicate instance names**, **0 unbound `${var}` placeholders** (payloads, `as_user_id`, path templates and asserts), all 5 `excluded_because` targets exist by name, and all **53 error codes** appear in at least one design instance. **59 worked-example numbers re-derived by code from the declared formulas and constants — 0 mismatches** (invoice builds, per-line-vs-summed rounding delta 29360 vs 29358, loyalty split 1120→336/784, trip-fee remainder 2334/2333/2333 = 7000, capacity totals, calendar dates and weekdays).

### F — Final counts
| | |
|---|---|
| Entities | **19** |
| Endpoints | **86** |
| State-machine axes | **18** (17 non-linear; parallel axes on Horse and on Appointment) |
| Transitions | 93 |
| Calculations | **29**, of which **7 dual-variant** (labor ROUTINE/WARRANTY, minutes STANDARD/SEDATED, cycle ROUTINE/THERAPEUTIC, cancel ADVANCE/LATE/ONSITE, loyalty STANDARD/PREMIER, tax TAXABLE/EXEMPT, price ESTIMATE/FINAL) |
| Error codes | **53** |
| Ladder rungs | **53** (rungs 29–34 are the 5 ordered `gate_precedence` gates) |
| OCC rules | **4** (Route, Appointment, LamenessCase, Client) |
| Conservation invariants | **7** (cents ×3, pairs ×3, capacity units/minutes) |
| Cascades | A=**depth 6**, D=depth 5, C=depth 4, B=depth 3 |
| Declared constants | **64** (0 undeclared) |
| Roles | 6 (peer_roles; 2 entity-backed) |
| §1.8 instances | **18** (9 rule_ids × 2) |
| §1.9 instances | **70** (65 with full `test_recipe`, 5 `excluded_because` stubs) |

Two counts land one above the stated target bands — 53 error codes and 53 ladder rungs (band 40–52) — because splitting the fiscal rate-card rung out of the shop-stock rung was a correctness fix, and dropping either `ERR_RESET_LIMIT_REACHED` or `ERR_BARN_MISMATCH` to hit 52 would have left a declared constant or a real cross-entity check unenforced. Everything else sits inside the requested band.

**Orchestrator independent verification:** `yaml.safe_load` OK on all three; `SCAFFOLD.yaml` carries neither design key; entities 19 / endpoints 86 / errors 53 / validations 53 re-counted from the parsed YAML; independent ALL_CAPS sweep → 64 declared constants, 18 residual tokens all gate ids (`GATE_*`), invariant ids (`INV_*`), or enum/discriminator members (`STANDARD_TIER`, `PRODUCT_TAXABLE`, `BY_SERVICE_DATE`, …) — **0 undeclared value-bearing constants**.

## Step 3: Copy INSTRUCTION.md — 2026-08-09T05:38:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0938_farrier_mobile_hoof_care/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-09T05:56:00.000Z

PRD written to `workspace/PRD.md`. Neither design index was opened; no sibling task directory was read. The document was built in nine bounded increments and assembled, never in one oversized write.

**Structure:** §1 Introduction · §2 Global Specifications (2.1 roles/identity, 2.2 verbatim envelope, 2.3 pagination/ordering/filters, 2.4 common properties + logical clock + date arithmetic, 2.5 money/basis points/rounding order, 2.6 the five ordered gates, 2.7 the full 53-rung ladder in priority order, 2.8 OCC, 2.9 the seven conservation invariants, 2.10 the four chains, 2.11 per-entity serialized shapes) · §3 nine workflow subsections · §4 the 4-column endpoint table plus §4.1 a per-endpoint input/output/refusal index · §5 the 2-column error table.

**Self-audit (6a–6f)**
- **a) Error codes** — 53 required, 53 present, **0 missing**.
- **b) Endpoints** — 86 required, all 86 appear with method + path in §4's table *and* in §4.1 with request fields (optional marked `?`), response shape, success status, and their reachable-refusal list. §4.1's union covers all 53 codes.
- **c) Constants** — 64 required, all 64 appear by name **and** with their literal value, scattered into the business statements that use them.
- **d) Ladder** — all 53 rungs stated in §2.7 with an explicit position. Gates sit at 28–33 (1a, 1b, 2, 3, 4, 5), OCC at 24–27 above them, existence at 4–20 above payload shape at 21–23. Three ordering consequences called out explicitly (units-before-minutes, credential-before-stock, live-prescription-before-limb-scope).
- **e) Response fields** — all 19 entities' full field lists in §2.11, `InvoiceLine` explicitly lacking `updated_at`/`version`. Contract 1: **138 required names, 0 missing**. Contract 3 path purity: 1167 §3 backtick tokens scanned, **0 violations**. §2.2 matches the canonical block byte-for-byte.
- **f) Size** — **673 lines, 19,438 words.**

**Friction points (13, all marked "Open point … must adopt one reading")**
1. §2.6 — gate 4 on a brand-new appointment: empty service-line set satisfies the corrective escape clause vacuously vs. routine booking for a held horse refused with `ERR_HORSE_ON_HOLD`.
2. §2.6 — gate 5 eligible set for reminder acknowledgement: `SCHEDULED` only vs. `SCHEDULED` + `CONFIRMED`.
3. §3.2 — SKU creation mints a `VAN` bucket per *existing* farrier vs. per *`ACTIVE`* farrier.
4. §3.2 — negative `delta_pairs` driving a bucket below zero: written as-is vs. refused with `ERR_VALUE_OUT_OF_RANGE`.
5. §3.4 — stop insertion at an occupied `sequence_index`: shift incumbents vs. `ERR_VALUE_OUT_OF_RANGE`; and whether the exchanged stop rows advance their own `version`.
6. §3.5 — a service line added to an *attached* appointment that breaches a cap or van stock: apply rungs 49/50/51 vs. let it through.
7. §3.5 — eligible appointment set for line *addition*: `{UNROUTED, SCHEDULED, CONFIRMED}` vs. also `IN_PROGRESS`.
8. §3.7 — an `UNROUTED` visit cancelled with under 3 days' lead: follow the `LATE` tier vs. refuse with `ERR_APPOINTMENT_NOT_ELIGIBLE`.
9. §3.8 — the auto-minted successor's `vet_present` for a sedation horse: true vs. the default false.
10. §3.8 — reminders minted both at successor creation and at attachment: four rows vs. two.
11. §3.8 — `ERR_REMINDER_SUPPRESSED`'s catalogue condition includes ineligible appointment status, which the gate ladder routes to `ERR_APPOINTMENT_NOT_ELIGIBLE` at a higher rung.
12. §3.9 — trip-fee re-allocation after stop completion: one-shot vs. recomputed when the billable set changes.
13. §3.9 — invoice issue's "or the appointment is UNROUTED": literal `status` test vs. a null `route_stop_id` test.

Two further gaps were resolved determinately rather than left open: `ROUTE_DAY_START_MINUTE` (480) is stated as a declared-but-unenforced planning reference, and rung 34's entity list was extended in §2.7 to cover `Farrier.status` and `ServiceLine.status`.

## Step 5: Generate unit tests — 2026-08-09T06:28:00.000Z

**Generated:** `test_helpers/` (`constants.py`, `types.py`, `api_errors.py` (54 codes + status map), `api_client.py` (one method per PRD §4 endpoint), `assertions.py`, `factories.py`, `test_users.py`, `fixtures.py`, `__init__.py`) and `test_suite/` (`conftest.py` + 10 test files), **6250 lines** total. All files written in bounded increments.

**Counts:** Queue A **18 instances, 18 translated, 0 skipped** → 36 tests (exactly 2 per instance). Queue B **70 instances, 5 `excluded_because:` stubs (not translated, all 5 cross-references verified to resolve), 65 non-stub, 65 translated, 0 skipped**. `def test_` = **101**; `Design:` tags = **101**; every tag resolves to a real instance; no stub translated. **Zero** skip/skipif/xfail markers. Two queue-A instances realized as ceiling-admitted / one-over-refused **pairs** (`next_stop_must_clear_predecessor_end_plus_its_own_travel_buffer` 575 refused / 581 accepted; `route_units_landing_exactly_on_the_cap_is_accepted` 44 accepted with its sibling corner instance covering 48 refused).

**Verification:** `compileall` clean; `pytest --collect-only` collects all 101; static name-resolution audit clean; every `api.<method>` exists on `ApiClient`. **206 quoted PRD fragments** in docstrings, all 206 survive a whitespace-normalized literal match against `PRD.md`. Every response-field subscript appears verbatim in PRD.md. `assert_same_instant()` / `assert_same_date()` used for every temporal assertion — no literal-rendering assertion anywhere. Only `is_valid_uuid` asserted for ids. `plus_days`/`plus_weeks`/`lead_days` are `timedelta`-based; calendar arithmetic only in `weekday_token()` (proleptic Gregorian, MON=0) for snap-forward/served-weekday. Fixture overshoot checked: composites layered, `setup_scheduled_visit` deliberately leaves the route `DRAFT`.

**Numeric re-derivations — every index number recomputed and agreed:** sedation surcharge `round_half_up(6524·1250/10000)=816` → line 7340, subtotal 29360 (vs the incorrect combined 29358); loyalty `round_half_up(37348·300/10000)=1120`, product leg 336, labour leg 784, taxable base 10864, tax 788, total 37016; uplift invoice 40012 / estimate 37200; trip fee 7000/3 → 2334/2333/2333, multi-horse 440, totals 10694/10693/10693; service minutes 86/104/110/84/128/66/38/32; units 12/16/20/9; pairs `ceil(3/2)=2`; route meters 44 units, 319/235/101/149/45/400 minutes.

**One index disagreement found and resolved:** `corner_appointment_listing_is_paginated_with_total_count_and_has_more` — its `distinguishing_aspect` prose says "has_more true" while its own `assert` list says `false`; derivation from §2.3 (offset 1 + 2 rows = 3, not < total_count 3) gives **false**. Asserted false.

**One assertion omitted on derivability grounds** (not a friction point): `clock_advance_expires_prescription_and_strips_corrective_lines` — index asserts `service_minutes == 6` / `committed_minutes == 21` after every line is removed; PRD admits two readings on whether handling survives an empty line set. Kept `service_units == 0`, the four `REMOVED` line statuses, and `Route.committed_units == 0`; omitted both minute figures.

**Friction cross-check (13 points):** 1 CLEAN · 2 AGREEMENT-BY-CONSTRUCTION (ack issued only while `SCHEDULED`, in both candidate sets) · 3 AGREEMENT-BY-CONSTRUCTION (both farriers asserted `ACTIVE` before SKU creation → same rows under either reading) · 4 CLEAN (only negative adjustment is 3→2) · 5 CLEAN (insertions always at `stop_count+1`; reorder test never asserts a stop's `version`) · 6 CLEAN (no test adds lines to an attached appointment) · 7 CLEAN (every addition targets `UNROUTED`) · 8 CLEAN (leads 9 and exactly 3, both `ADVANCE`) · 9 AVOIDED-BY-OMISSION (the sedated visit's successor carries no assertion at all) · 10 AGREEMENT-BY-CONSTRUCTION (the counted successor is never attached → 2 under both readings) · 11 CLEAN (suppression tested against a `SCHEDULED` appointment) · 12 CLEAN (shares read immediately, no later status change) · 13 CLEAN (no test calls issue/void).

## Step 6: Generate implementation — 2026-08-09T06:28:00.000Z

`workspace/implementation/` — Python + Flask, **41 modules / 5,004 lines** plus a 12-line `start.sh` and `requirements.txt`. Layered as `core/` (clock, ids, store, envelope, auth, validation, errors, constants), `domain/` (gates, ladder helpers, rollups, rates, inventory, reservations, route meters, invoices, lameness/expiry cascades, scheduling, clients), `routes/` (14 blueprints). Written incrementally.

**GATE 1 — endpoint completeness (programmatic).** 86 scaffold endpoints vs. 87 app routes; **MISSING = 0**, EXTRA = 1 (`GET /static/<path>`, Flask's built-in, expected).

**GATE 2 — HTTP self-verification on live boots.** Four scripts, **213 checks, 0 failures**: full happy path; both branches of all 7 dual-variant calculations (STANDARD/SEDATED minutes 54 vs 32, ROUTINE/WARRANTY labour, PRODUCT_TAXABLE/EXEMPT, STANDARD/PREMIER loyalty 150 vs 300, ESTIMATE/FINAL, ROUTINE/THERAPEUTIC cycle, ADVANCE/LATE/ONSITE tiers); all 7 conservation invariants (trip-fee split `[1334,1333,1333]`=4000, bucket balance, system pairs across dispatch/receive, reserve/release round trip, capacity round trip, loyalty split, invoice total); the **depth-6 lameness cascade end to end** (hop1 hold_applied → hop2 HOLD → hop3 BLOCKED+detached → hop4 RELEASED → hop5 flag flip → hop6 REQUESTED transfer CANCELLED, plus 3b stop VOIDED and 4b route reverted to DRAFT); the depth-5 expiry cascade; and **all 53 error codes reached at least once**.

**GATE 3(a) — timestamps.** One producer, `core/timeutil.render_instant`. Observed live: server-minted → `.mmmZ` exactly 3 digits (`2026-05-04T00:00:00.000Z`); caller-supplied → **byte-verbatim** (in `2026-05-04T00:00:00Z` → out `2026-05-04T00:00:00Z`, not `.000Z`; `...06:30:00.500Z` preserved); derived → style of the source (`next_due_on = 2026-06-22`, `YYYY-MM-DD`).

**GATE 3(b) — enum routing, closed list.** `ERR_INVALID_ENUM` reached from exactly: `zone`, `served_weekdays[]`, `certification_level` (POST /farriers + recertify), `material`, `reason` (deactivate), `lines[].service_type`, `limb_scope[]`, `warranty_reason`, `delivery_outcome`, `direction`. Two catalogue entries on the list but unreachable — `Appointment.visit_kind` (no endpoint accepts it) and `LimbState.limb` (system field). **No other field routes here.** Everything else: query filters never error; missing/mistyped body fields → `ERR_VALIDATION`; numeric/date bands → `ERR_VALUE_OUT_OF_RANGE`; body FKs → `*_NOT_FOUND`; wrong state → `ERR_INVALID_STATE`/gate code. HTTP-verified on both sides.

**GATE 4 — EADDRINUSE-proof startup.** Pre-bound socket with `SO_REUSEADDR`, 24×0.25s (~6s) retry then hard `sys.exit(1)`, served via `make_server(..., threaded=True, fd=sock.fileno())`. `start.sh` probes with `importlib.util.find_spec` (boot 0.27s). **20 consecutive kill -9/relaunch cycles: 0 start failures, 0 orphans, 0 lingering listeners.** Occupied-port probe: retried 6.09s then exited 1. (Across ~98 total cycles one isolated start failure occurred while another session saturated the host; 84 cycles since were clean.)

**GATE 5 — storage/purity.** In-memory dicts only. Grep for `sqlite|json.dump|pickle|/tmp/|datetime.now|utcnow|time.time()` → **no matches**. All 17 listable tables report `total_count=0` on a fresh boot.

**GATE 6 — determinism.** Ids are `%012x` monotonic counter + random tail, valid RFC-4122 v4 UUID strings; ascending id order == creation order. List ordering is `(created_at, mint-sequence)` — `id` is never a sort key.

**The 13 adjudications** (rule applied: the reading that keeps the largest number of PRD-declared behaviors reachable)
1. Gate 4 on a new appointment → **refuse** `ERR_HORSE_ON_HOLD` (§4.1 declares it reachable on `POST /appointments`; only refusal keeps it so). Warranty-revisit is *not* gate-4 guarded.
2. Gate 5 on acknowledgement → **`SCHEDULED` + `CONFIRMED`** (§3.8's conditional can only be false under this reading).
3. VAN buckets on SKU creation → **per existing farrier row, any status** (ACTIVE-only leaves a reactivated farrier permanently bucket-less).
4. Negative `delta_pairs` → **refuse** `ERR_VALUE_OUT_OF_RANGE` (the only way that declared refusal is reachable on `/adjust`).
5. Occupied `sequence_index` → **shift incumbents** (refusing strands the declared range `1..stop_count`); **both exchanged stops advance their own `version`**, applied consistently to shifted incumbents.
6. Line added to an attached visit breaching a limit → **apply rungs 49/50/51 atomically**; a refusal writes nothing.
7. Eligible set for line addition → **{UNROUTED, SCHEDULED, CONFIRMED}**, exactly as §2.6 states.
8. UNROUTED cancelled at short notice → **follow the LATE tier** (refusing leaves the visit permanently uncancellable since the lead only shrinks).
9. Successor's `vet_present` → **true when the horse requires sedation** (no endpoint can edit `vet_present`, so `false` strands every sedation horse's successor unattachable forever). Same for the warranty revisit.
10. Reminders minted twice → **unconditional; four rows** on an auto-minted successor later attached.
11. Ineligible appointment on send → **the gate wins**, `ERR_APPOINTMENT_NOT_ELIGIBLE` (rung 33); `ERR_REMINDER_SUPPRESSED` reserved for the sibling window. Both stay reachable.
12. Trip-fee re-allocation → **one-shot at stop completion** (every billable appointment is already terminal, so a recompute trigger would be dead code).
13. Invoice issue's "UNROUTED" → **test the attachment (`route_stop_id` is null)** (the literal-status reading makes a LATE-cancellation invoice permanently unissuable).

**Notes and unverified claims**
- Day/week arithmetic is elapsed-duration throughout (`timedelta`); calendar arithmetic only for the weekday token (proleptic Gregorian, MON=0).
- Rounding order: per-line-then-sum for labour (each sedation surcharge rounded on its own), once-per-total elsewhere; the loyalty split rounds the *product* leg and lets labour absorb the remainder. All half-up on integers, no floats.
- **Version increments** follow §2.4's unconditional "every mutation of that row", so a completion advances the appointment **twice** (status step + `billing_status`→INVOICED). A judgement call where §2.4's general rule and §3's side-effect lists can be read as disagreeing.
- **Unverified reachability hypotheses (to be checked by reading the code, not taken on faith):** (a) `Appointment.visit_kind` and `LimbState.limb` never reach `ERR_INVALID_ENUM`; (b) `ERR_NOT_RESOURCE_OWNER` is unreachable on list endpoints; (c) rung 47 (`ERR_SEDATION_VET_REQUIRED`) is unreachable at attachment for auto-minted successors given adjudication 9.
- Two §4.1-vs-§3 mismatches resolved in favour of §3: `POST /appointments/{id}/start` and `.../no-show` enforce the stop-`ARRIVED` precondition with `ERR_INVALID_STATE` (rung 34 covers `RouteStop.status`) although §4.1 omits that code. Also §2.11 says `completed_on` is set for `CANCELLED_*`, but §3.7 states each tier "in full" without it, so cancellations leave `completed_on` null.

**Orchestrator isolation verification:** `grep -rIl "test_suite|test_helpers|conftest" workspace/implementation/` → **empty**; `grep -rIl "workspace/implementation|from implementation|import app" test_suite/ test_helpers/` → **empty**. `def test_` = 101 == `Design:` tags 101 (36 Difficulty + 65 Corner). 0 skip/xfail/skipif. Impl purity grep → 0 matches.

## Step 7: Test and iterate — 2026-08-09T07:35:00.000Z

### Result: clean — 8/8 rounds, 101/101, 0 failures, 0 errors

**Iterations:** 3 sweeps. Wall time ~2.5 min/sweep (2 waves × ~62 s/round). Sweep 1: 3 logic failures. Sweep 2: 0 logic failures + 1 saturation error. Sweep 3 (final): fully clean.

**Tests deleted: none.** All 3 failures were genuine defects (1 implementation, 2 test fixtures) — no test rode a friction point or an unstated rule.

### Fixes applied

**`implementation/routes/appointments_bp.py`** — `new_appointment()`: removed the `recompute_appointment_rollups()` call at mint time. It folded the 6-minute `HORSE_HANDLING_MINUTES` term into a brand-new appointment (`service_minutes == 6`), contradicting §3.5's verbatim *"its `service_units`, `service_minutes`, `estimated_total_cents`, `cancellation_fee_cents` and `trip_fee_share_cents` all start at 0."* The recompute rule is scoped by the same section to *"after every change to the line set"*, and minting is not one. Verified safe across all 3 callers (create, cycle successor, warranty revisit — all mint with an empty line set) and against every other `service_minutes` assertion in the suite.

**`test_suite/test_03_routes_and_stops.py`** — `test_reorder_swaps_the_two_sequence_indices`: the fixture asked to move stop 2 to `planned_start_minute` 480 while the sibling it swaps past also sat at 480. Since reorder writes a fresh start minute for the moved stop *only*, the sibling became the later of the pair at the same minute — a real violation of §3.4's buffer rule, which §3.4 says is re-checked on reorder. The implementation was correct. Changed to 420 (the barn's `access_open_minute`); 480 ≥ 420 + 0 service + 15 travel clears it.

**`test_suite/test_07_running_the_route.py`** — `test_cancelling_a_cancelled_appointment_is_not_eligible`: setup created no rate card, so the *first* cancel died on rung 53 before gate 5 could ever be the thing under test. Rung 53 names *"appointment cancellation"* unqualified by tier, and §4.1 lists `ERR_NO_EFFECTIVE_RATE_CARD` among `/cancel`'s refusals — the implementation was correct. Added `create_active_rate_card()`.

**`test_helpers/`** — no changes needed.

### Audits

- **A — real:** 8×101 individual rows, status set exactly `{passed}`, sorted name lists byte-identical across all 8 rounds, 101 unique names. `def test_` = 101 = `Design:` tags = collected count. 0 skip/xfail/skipif. Zero tracebacks; exactly one `Killed` per round, immediately after the first test name (the expected pre-boot server swap).
- **B — isolation observable:** PRD §3.2 declares *"a `sku_code` that must be unique across all SKUs"*, enforced at `inventory_routes.py:34-35`. The default payload always claims `"ST-1"`, and it is claimed **43 times across 9 of 10 test files**. A failed reset would refuse the second claim. Holds in all 8 rounds.
- **C — friction cross-check (all 13 safe):** CLEAN — 1 (no test creates an appointment for a held horse; the two attach tests carry a `NEW_SHOES` line, so the corrective escape clause fails under both readings), 4 (only negative adjust is 3→2, never below zero), 5 (every insertion is at `stop_count+1`, never occupied; no stop `version` asserted), 6 & 7 (**every** line addition in the suite targets a freshly created `UNROUTED` appointment — attachment always follows), 13 (no issue/void call exists). AGREEMENT-BY-CONSTRUCTION, re-derived — 2 (ack asserted `SCHEDULED` immediately prior, in both candidate sets), 3 (every `create_sku` runs with **zero** farriers existing; no SKU is ever created after a deactivation), 8 (leads 9 and exactly 3, both ADVANCE; the fourth cancel short-circuits at ownership), 10 (the counted successor is never attached → 2 rows either way), 11 (suppression tested against a `SCHEDULED`, i.e. eligible, appointment), 12 (7000//3 = 2333 r1 → 2334/2333/2333 = 7000, read immediately with no later billable-set change). AVOIDED-BY-OMISSION — 9 (no successor `vet_present` assertion anywhere; no successor is ever attached). **0 DEPENDS.**
- **D — near-miss register (closest first):** ① `test_horse_on_hold_pre_empts_the_van_stock_shortfall` — fair only because the fixture passes `service_type="NEW_SHOES"`; one changed constant (`"CORRECTIVE"` with a covering prescription, or `limbs=()`) makes gate 4's escape clause vacuous → friction 1. ② the reminder-acknowledgement test — the fixture already holds a still-`PENDING` `secondary` reminder; **one added `acknowledge_reminder(secondary)` call** after the appointment reaches `CONFIRMED` lands exactly on friction 2. ③ suppression test — one extra call (cancel/complete first) → friction 11. ④ successor reminder count — one extra call (attach the successor) → friction 10. ⑤ trip-fee test — one extra call (no-show one of the three after completion) → friction 12. ⑥ `test_non_contiguous_sequence_index_is_rejected` — uses index 3; index 1 is in-range *and* occupied → friction 5. ⑦ the repaired reorder test — one added assertion on the sibling's `version` → friction 5's second half. ⑧ `test_farrier_creation_mints_a_van_bucket_per_existing_sku` — two changes (create+deactivate a farrier before the SKU) → friction 3. ⑨ the 3-day cancels — two changes (drop the attach *and* shorten the lead) → friction 8.
- **E — provenance:** PASS ×4. All asserted field names verbatim in PRD (the 23 non-matches are the tests' own `TEST_DEFAULTS`/`world`/header dict keys). All 66 constants match their PRD-declared values; every distinctive literal re-derived (e.g. sedation surcharge `round_half_up(6524×1250/10000)=816` → line 7340, subtotal 29360 vs the incorrect sum-then-round 29358; loyalty 1120→336/784). All 23 temporal assertions semantic via `assert_same_instant`/`assert_same_date` — zero rendered-string comparisons. All index assertions trace to §2.3's ordering rule, the limb-order exception, §3.5's supplied-order rule, or a preceding `len == 1`.
- **F — generator claims:** (a) **CONFIRMED** — 11 enum call sites enumerated; `visit_kind`/`limb` are never read from a body (probes: bogus values silently ignored, 201). (b) **REFUTED** — `GET /horses/{id}/limb-states` and `GET /invoices/{id}/lines` return arrays *and* guard ownership; both return 403 `ERR_NOT_RESOURCE_OWNER` for a non-owning ClientUser. (c) **REFUTED** — `PATCH /horses/{id}` with `requires_sedation: true` **after** the successor is minted reaches rung 47 at attachment (422 `ERR_SEDATION_VET_REQUIRED`, executed end to end). Neither refutation affects fairness — no test asserts unreachability, and both are PRD-sanctioned (§4.1 lists both codes on those endpoints).
- **G — routes:** 86/86, 0 missing, 1 expected extra (`GET /static/<path>`).
- **H — no drift:** `find … -newer results.1.json -name '*.py'` is empty; the green result matches the code on disk.

### Warnings for a future run

1. **Host saturation is the dominant noise source here, not the port race.** Sweeps 1 and 2 each produced 1–2 `could not be restarted` ERRORs, always `failed: 0`, always *different* tests, always in the wave running while 5–8 other tasks' `prd-bench-local-run` processes were live (load 6–8 on 8 cores). Zero code change fixed it; waiting for load < 3.5 did. The pre-bind + `SO_REUSEADDR` + ~6 s retry in `app.py` is intact — don't touch it. Load rarely drops below ~2.5 on this shared host, so a bounded wait for < 3.5 is the practical gate.
2. **Two unenforced-PRD-universal findings for Step 9** (no test exercises either, so both are pins, not bugs): PRD §4.1 declares `ERR_NOT_RESOURCE_OWNER` reachable on *every* collection list and §2.1 says rung 3 *"applies to every endpoint whose authorized set includes `ClientUser` or `Farrier`"*, yet `GET /horses` and `GET /appointments` return another client's rows to a non-owning ClientUser with 200. And §3.4 line 265 says a route may hold *"fewer than 8"* stops but its own operative clause admits 8 — the suite follows the operative clause (`stop_count == 8`), the same summary-vs-detail drift pattern flagged at task 0923.
3. **Adjudication 9's justification is sound but its corollary is false** — the successor carries `vet_present` true only for horses that required sedation *at completion time*; a later horse PATCH strands it exactly as the rejected reading would. Worth naming if this scenario recurs.

**Orchestrator independent re-verification:** all 8 `results.N.json` re-parsed → **101 individual rows each**, `passed=101 failed=0`, status set exactly `{'passed'}`, sorted-name sha256 `2a591fd8874d` **identical across all 8 rounds**; each `round.N.log` has `Killed` exactly once and **0 tracebacks**; `find test_suite test_helpers workspace/implementation -newer results.1.json -name '*.py'` → **empty** (no post-sweep drift).

## Step 8: Finalize PRD — 2026-08-09T07:21:00.000Z

`PRD_FINALIZED.md` written. **673 → 673 lines (0 delta), 19,438 → 19,578 words (+140, +0.72%), 145,382 → 146,387 chars (+1,005, +0.69%).** All edits inline; no sections, paragraphs or open points added or removed. The 13 "Open point …" passages are byte-identical.

**Changes (4 sites, 5 insertions)**
- §3.5 (roll-up recompute rule) — insert — minting an appointment is not itself a line-set change, so a brand-new appointment's roll-ups stay at 0 until its first service line arrives, with none of the handling term folded in — `routes/appointments_bp.py:55-82`.
- §3.7 (completion, ordered side-effect list) — insert — the appointment's `service_units`/`service_minutes` are recomputed (`OMITTED` lines drop out, `PERFORMED` stay in) and `estimated_total_cents` is left as it stands — `routes/appointments_bp.py:248`, `domain/rollups.py:79-84`.
- §3.7 (completion, trailing sentence) — insert — the still-attached stop's `service_minutes`/`end_minute` and the route's committed totals are re-derived once the rest of completion has run — `routes/appointments_bp.py:286-289`, `domain/routecalc.py:26-38`, `domain/routeops.py:29-42`.
- §3.7 (warranty revisit mint) — insert — the revisit's five roll-up fields all start at 0 — `routes/appointments_bp.py:414-421` → `new_appointment`.
- §3.8 (auto-minted successor) — insert — same five fields start at 0 on the successor — `routes/appointments_bp.py:278-283` → `new_appointment`.

**Per-edit pre-edit search log (NO-NEW-MISMATCH rule)**
1. §3.5 recompute scoping — subject: *when* the recompute fires. Enumerated all four `recompute_appointment_rollups` callsites (`servicelines.py:208`, `:233`, `domain/lameness.py:134`, `appointments_bp.py:248`) + the mint path + `domain/rollups.py:32-44` (handling added unconditionally → empty line set recomputes to 6/24 min, not 0) + `routes/stops.py:218`. Adjustment: wrote "not *itself* such a change" and left the general clause untouched, so removing the *last* line (legitimately yielding 6 with zero lines) stays covered. Deliberately did **not** write a closed list of firing moments despite the grep being exhaustive, to avoid a false universal.
2. §3.7 completion recompute — enumerated the whole completion body `:210-290`, `domain/rollups.py:21-29`, the invoice pricing path (never reads the roll-ups), and all 4 `estimated_total_cents` write paths (**none** at completion). Adjustment: added the explicit "left exactly as it stands" clause, because §3.9's "refreshed on every service-line change" would otherwise have implied an estimate refresh the impl does not perform.
3. §3.7 stop/route follow-on — enumerated `:286-289`, `routecalc.py:26-38` (no status filter), `:40-61` (`COMPLETED` is inside `ROUTE_COMMITTING_STATUSES`), `routeops.py:29-42`. Confirmed an `IN_PROGRESS` appointment can never be detached, so "the stop the visit is still attached to" is never vacuous. Adjustment: said "the route's committed totals" rather than naming two fields (the helper also rewrites `stop_count`), and placed the sentence after the ordered list to match actual ordering.
4. §3.7 warranty-revisit zeros — enumerated `:391-422`, `:55-82`, `domain/serializers.py:39-44`. Adjustment: grounded the clause in "carries no service lines yet" so it cannot be read as importing gate 4 / the sedation rung into the revisit path (the revisit runs gates 3 and 5, not 4).
5. §3.8 successor zeros — enumerated `:267-284`, `:55-82`, `domain/scheduling.py`. Adjustment: listed only the five roll-up fields — no mention of `vet_present` (an open point, Step 9's business) or `origin_appointment_id`/`billing_status` (outside the subject).

**Sibling-derivation sweep — where the yield was.** `new_appointment` has exactly three callers. Create (§3.5) was **already explicit** — which is why the *implementation*, not the PRD, was the wrong side. The auto-minted successor (§3.8) and the warranty revisit (§3.7) were **both silent** on the five roll-up fields and each needed a pin. Sweeping "when does the recompute fire" across every roll-up mention: §3.5 add (explicit), §3.5 remove (explicit), §2.10/§3.6 expiry hop 5 (explicit), §3.4 route meters (reads only, explicit), §3.7 completion (**needed a pin** — the ordered side-effect list never mentioned the roll-ups even though the `PLANNED`→`OMITTED` split changes them). Item 2's sweep (which stop's minutes an operation writes) and item 3's (which operations demand an effective rate card) needed no pin. Two findings deliberately left for Step 9 as out of Step-8 scope: `check_adjacency`'s `focus_ids` narrowing, and the impl pinning `rate_card_id` on the LATE/ONSITE/no-show legs.

**Zero-edit items, each with its governing verbatim sentence quoted** — item 1's own fix site (§3.5's "…all start at 0" sentence), item 2 (§3.4's reorder + travel-buffer sentences), item 3 (§2.7 rung 53 + §4.1's `/cancel` entry). All three correctly required no PRD change.

## Step 9: Complete PRD — 2026-08-09T10:07:00.000Z

`PRD_COMPLETED.md` written. **673 → 675 lines (+2), 146,387 → 168,001 chars (+21,614), 63 changed/added lines. Heading diff empty — no new sections.**
(Note: Step 9 was interrupted mid-run by an API session limit after most edits were already applied, then **resumed from its transcript via SendMessage** rather than restarted — it reconciled the on-disk file against its finding list and applied the remainder.)

**Counts: 45 ambiguity-pins, 16 mismatch-revisions** (61 discrete changes over 63 lines).

**Q11 — all 13 frictions converted.** `grep -c 'Open point\|must adopt one reading'` → **0**; 13 blockquote pins. Every one verified against the code first; all 13 reported choices confirmed: 1 gate 4 refuses creation (`domain/gates.py:66-69`) and warranty-revisit is not gate-4 guarded (`appointments_bp.py:405-407`) · 2 ack set = SCHEDULED+CONFIRMED (`gates.py:111`) — **also fixed §2.6's operative gate-5 clause, which still said SCHEDULED alone** · 3 VAN bucket per existing farrier row, any status (`inventory.py:61-62`) · 4 negative balance refused (`inventory_routes.py:96-97`) · 5 shift incumbents, incumbents *and* both exchanged stops advance (`routes_bp.py:157-172`, `stops.py:100-114`, confirmed live) · 6 atomic 49/50/51 refusal (`servicelines.py:197-206`) · 7 `{UNROUTED, SCHEDULED, CONFIRMED}` (`gates.py:93`) · 8 UNROUTED short-notice → `CANCELLED_LATE` (`appointments_bp.py:319-326`, live) · 9 successor `vet_present` snapshot, **corollary confirmed** — `PATCH /horses` cannot retro-fit it, so rung 47 refuses at attachment · 10 four reminders (`scheduling.py:71-98`, live) · 11 gate wins, `ERR_REMINDER_SUPPRESSED` reserved for the sibling window (`reminders_bp.py:48-55`, live) · 12 one-shot at stop completion (`invoices.py:273-284`) · 13 issue tests the attachment, not the status (`invoices_bp.py:70-72`, live).

**Per-question yield**

| Probe | Findings | Note |
|---|---|---|
| **Q11** frictions | **13** | highest value, as briefed |
| **Q1** field consulted? | **10** | top code-walk vein: `home_barn_id`, `shoe_size_code`, `lifecycle_status`, `next_due_on`, `reported_on`, `current_sku_code`+`last_serviced_on`, `cycle_source`+`origin_appointment_id`, `credit_balance_cents`, `no_show_count_rolling`, `offset_days`/`due_on` |
| **Q7** version scope | **8** | completion/LATE/ONSITE/no-show = +2; ADVANCE = +1; route & stop steps **conditional** on the recomputed figures moving; reorder & insert shift-versions; bucket per counter move |
| **Q9** error precedence | **6** | ownership-vs-existence splits by endpoint shape; rung 21 sweeps the whole `lines` array before rung 22; element order dominates rungs 36–40; rung 34 before 35 on start |
| **Q6** cascade legs | **4** | hop 3b needs `PENDING`; 4b needs a *fall* from positive; expiry hop 5 also refreshes the estimate; re-scheduling chain numbering is causal not chronological |
| **Q2** quantifiers | **4** | both handed-down leads confirmed live |
| **Q3** derived vs stored | 3 | |
| **Q8** uniqueness/scope | 3 | |
| **Q12** Step-8 leads | 3 confirmed | rounding-order item was **dry** — PRD already pinned all three correctly |
| **Q13** hypotheses | 3 | `visit_kind`/`limb` enum routing genuinely unreachable |
| **Q5** list semantics | 1 (≈6 sub-points) | |
| **Q10** timestamps | 1 large | the three-case rendering policy was nowhere in the PRD |
| **Q4** serializer | **1** | **near-dry** — field lists matched §2.11 exactly; `InvoiceLine` verified as lacking `updated_at`/`version`. Only find: service-line addition emits `response_type` `"object"` for an array |

Most productive: Q11, Q1, Q7, Q9. Driest: Q4, and Q12's rounding item.

**Headline mismatches (not just silence)**
- §2.1/§2.7/§4.1 — **no list endpoint scopes or refuses by ownership**. Verified live: `GET /horses` returns another client's rows to a `ClientUser` with 200. Single reads *do* enforce (403). `ERR_NOT_RESOURCE_OWNER` is unreachable on every collection.
- §3.5 — attaching a **line-less** appointment advances neither the route's nor the stop's `version` (verified live: route stayed at v2).
- §3.7 — "All five gates run first" on start is wrong; only gates 1, 4, 5 run. Gate 3 is not consulted, matching §2.6's own guard list.
- §3.7 — the client's `completed_visit_count` rises **before** the invoice is priced (§3.7 listed it after; §3.9 step 5 requires the former).
- §3.4 — "fewer than 8 stops" contradicts its own operative clause; it is **at most 8**.

**Genuine implementation bugs — reported, NOT pinned as intended, code untouched**
1. **`routes/servicelines.py:198-201` — the capacity re-check undercounts the minute delta.** `delta_minutes` sums only the per-limb chair minutes of the lines being added, but `service_minutes` also carries the handling term (6 min, or 21 sedated), folded in only once the first line exists (`domain/rollups.py:37-44`). So the **first** line addition to an already-attached, previously line-less appointment can carry the route past `ROUTE_MAX_MINUTES_PER_DAY`; `settle_route` then recomputes from scratch and writes the over-cap figure. Step 9 pinned the projection basis factually in §3.5 without asserting the cap holds.
2. **`routes/lameness_bp.py:88-107` — resolving a `PRESCRIBED` case revokes its `ACTIVE` prescriptions but never re-runs the cycle derivation**, unlike the explicit revoke path (`:249`). §3.8 says the derivation re-runs "on prescription revocation". The horse keeps a `next_due_on` computed from a now-`REVOKED` prescription. Pinned as observed behaviour with the divergence stated plainly.
3. **Design consequence, not a defect:** `domain/routecalc.py:26-38` computes a stop's `service_minutes` with *no* status filter while `recompute_route_totals` filters by `ROUTE_COMMITTING_STATUSES` — so a no-showed horse keeps lengthening its stop's `end_minute` against the barn's access window while contributing nothing to the route meters. Pinned in §3.4 as intended.
4. `domain/routecalc.py:105-140`'s `focus_ids` narrowing (the Step-8 lead) confirmed: a pre-existing buffer violation between two untouched stops can persist indefinitely. Pinned in rung 46 as intended.

**Orchestrator final verification:** `diff <(grep '^#' PRD.md) <(grep '^#' PRD_COMPLETED.md)` → **empty** (no new sections across BOTH Step 8 and Step 9); `grep -c 'Open point'` and `grep -c 'must adopt one reading'` on PRD_COMPLETED.md → **0 / 0** (all 13 frictions pinned); `find test_suite test_helpers workspace/implementation -newer results.1.json -name '*.py'` → **empty**, proving Steps 8 and 9 touched no code and the 8×101 green result corresponds to the code on disk.

## PIPELINE COMPLETE — 2026-08-09T10:10:00.000Z

101/101 tests passing on all 8 sweep rounds. 0 deletions, 1 implementation fix, 2 test_suite fixes, 0 test_helpers fixes.
