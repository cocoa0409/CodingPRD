# Worklog — task_1756_aerial_firefighting_contract_operations

## Step 1: Create task directory — 2026-08-14T13:54:00.000Z

Pre-assigned directory `tasks/task_1756_aerial_firefighting_contract_operations/` with `workspace/` already created by pipeline dispatch; treated as DONE per entrance instructions (no index scan, no writes outside this directory).

## Step 2: Generate scaffold — 2026-08-14T14:49:48.850Z

Scaffold generation complete. All three artifacts written to `/home/ubuntu/github/CodingPRD/tasks/task_1756_aerial_firefighting_contract_operations/` and lint-verified clean on the first full pass.

## Files written

- `SCAFFOLD.yaml` — §1.0–§1.7 (no `scaffold_difficulty_design`/`scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:` (§1.9)

## Counts

| Element | Count |
|---|---|
| Entities (§1.1) | 14 |
| State machines (§1.2) | 10 |
| Concurrency rules (§1.2.1) | 2 (both OCC, 412) |
| Calculations (§1.3) | 8 |
| Validations (§1.4) | 13 priority levels |
| Endpoints (§1.5) | 66 |
| Error codes (§1.6) | 40 |
| Roles (§1.7) | 7 |
| §1.8 instances | 18 (2 per each of 9 rules) |
| §1.9 instances | 45 active + 7 `excluded_because` stubs, across all 9 guide sections |

Lint verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (796 calls scanned). Additional audits: zero unbound `${var}` placeholders (instance-wide scope), all `grounds:` resolve, no forbidden concurrency vocabulary, name uniqueness across the union of both design files, all enum values producible, all 40 errors triggerable.

## Key design decisions (harder-than-expert calibration)

- **Archetype**: ledger reconciliation (carrier-provisional vs agency-reconciled billing) + compliance/audit secondary; layers: dual-variant calculation, cascading side effects, rate/threshold triggers, optimistic concurrency. Flat topology, cyclic machines, segregation-of-duties role model.
- **Dual-variant calcs on two domains**: invoice billing (PROVISIONAL carrier basis 1,500,000 vs RECONCILED agency basis 1,470,000 cents for identical logs) and crew-duty projection (chronological `flown_tenths` 75 vs forward-looking `projected_tenths` 85 on the same data).
- **Combinatorial modes (a)+(b)+(c)**: EU/CWN availability charge (conditional min-threshold prorate), per-sortie-round-then-sum flight billing (540,000 vs forbidden 510,000 cents — order pinned), and invoice net with pinned evaluation order (penalty = 5% of availability subtotal when compliance < 0.98; verified literal net 1,252,500).
- **Cascades**: depth-3 from inspection FAIL (aircraft SUSPENDED → availability periods UNAVAILABLE → DRAFT invoice re-derived) and depth-4 from a flight log hitting 80 tenths (duty day → FATIGUE_HOLD → conditional release of only ASSIGNED assignments → dispatch order FILLED→ACCEPTED bubble-up).
- **Priority conflicts on three different category pairs**: state>fiscal (suspended contract + exhausted season cap), safety>referential (fatigue hold + wrong-contract pilot), state>constraint (suspended contract + duplicate availability date).
- **Boundary precision**: 80-tenths flight limit (exactly 80 allowed), 30.0-minute reload SLA (strict `>`; 30.0 not a breach, 30.3 is), 840-minute crew day (inclusive), 60-minute rest gap (inclusive), reconciliation tolerance ±1 tenth, acceptance deadline inclusive, season-end date inclusive, season flight cap (`>=` at dispatch, `>` at log).
- **Temporal overlap with two interval semantics**: aircraft planned windows are half-open (back-to-back 10:00/10:00 adjacency legal); pilot windows require a 60-minute rest buffer (30-minute gap rejected even though nothing intersects).
- **Compensating invariants on two quantity types**: money (`season_billed_cents == Σ net_cents over {SUBMITTED, DISPUTED, RECONCILED, PAID}`; submit+void pair conserves) and headcount (`filled_count == count of assignments in {ASSIGNED, EN_ROUTE, ON_INCIDENT}`; create+release pair conserves, driving compound order status).
- **OCC (only sanctioned races)**: `expected_contract_version` on invoice create, `expected_dispatch_order_version` on assignment create — both pass the serial-observability filter (stale-version rejection testable with two strictly sequential calls).
- **RBAC edges**: Pilot is `entity_backed: CrewMember` (ownership checks on flight-logs/launch/arrive/drop); segregation of duties enforced across opaque operator ids (`submitted_by != reconciler`); 6 business roles + clock-only SystemAdmin; logical clock endpoint with the mandated `2026-08-01T00:00:00Z` startup default.

## Step 3: Copy shared files — 2026-08-14T14:50:10.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1756_aerial_firefighting_contract_operations/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T15:08:24.340Z

All checks pass. Generation complete.

## Summary

**Output written:** `/home/ubuntu/github/CodingPRD/tasks/task_1756_aerial_firefighting_contract_operations/workspace/PRD.md` — 320 lines.

**Section list:**
- §1 Introduction (2 paragraphs — business context of USFS/CAL FIRE exclusive-use vs call-when-needed contracts, plus the dual-basis billing and hard-safety-gate design pressures)
- §2 Global Specifications (10 subsections): 2.1 RBAC, 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`), 2.3 Pagination (incl. all list-filter query params), 2.4 Common Resource Properties (incl. the `updated_at`/`version` absence for FlightLog/InvoiceLineItem/AgencyRecord), 2.5 Nested Resource Retrieval (left-to-right 404 ordering), 2.6 Money/Tenths/Rounding, 2.7 The Logical Clock, 2.8 OCC, 2.9 Validation Order and Error Precedence (13-priority chain with a worked precedence example), 2.10 Season Ledgers and Cascades
- §3 Business Logic (8 subsections): 3.1 Contract lifecycle, 3.2 Fleet/crew/carding, 3.3 Availability and the daily charge, 3.4 Incidents and resource ordering, 3.5 Assignment gate chain, 3.6 Flight operations/fatigue/demobilization, 3.7 Retardant SLA, 3.8 Invoicing/reconciliation/payment
- §4 Endpoint Definitions (4-column table, 66 rows = 66 scaffold endpoints)
- §5 Error Code Catalogue (2-column table, 40 rows = 40 scaffold errors)

**Contract reports:**
- **Contract 1 (Field-Name Coverage):** 114 required identifiers (all `entities[].fields[].name`, endpoint `input` lists, query/path params, common fields, headers) — 114 present, 0 missing. PASS
- **Contract 2 (Rule Coverage):** all 13 validations expressed in priority order with paired error IDs; both OCC rules (`expected_contract_version` on invoice create, `expected_dispatch_order_version` on assignment create, `ERR_STALE_VERSION`/412, "no other endpoint takes a version field"); every state-machine transition with preconditions and side effects (including the 3-link aircraft-fail cascade, 4-link fatigue cascade, fill-band bubble-up, invoice negotiation loop); all 8 calculations in reconstructible prose (pinned per-sortie rounding with the 540,000 vs 510,000 worked example, 6-step invoice composition with exact-rational 0.98 compliance compare, matched/unmatched reconciliation branches with the 1,500,000 vs 1,470,000 example, reload-turn tie-break rules, both invariants); every validation `applies_to` scope enumerated; sibling branches (dual close paths, dual decard paths, excuse from OFFERED/CONFIRMED, void from 3 states) rendered with equal density. PASS
- **Contract 3 (§3 Path Purity):** 502 backticked tokens scanned in §3, 0 path/method violations. PASS
- §2.2 verbatim block: byte-identical PASS. All 40 error IDs, 7 roles, and all enum/state strings (including `COMPLETED` after one repair) present in backticked prose.

Note: the two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## Step 5: Generate unit tests — 2026-08-14T15:41:35.914Z

All checks pass. Work complete.

## Summary

**Files written** under `/home/ubuntu/github/CodingPRD/tasks/task_1756_aerial_firefighting_contract_operations/`:

`test_helpers/` (Stage 1):
- `types.py` — 14 entity TypedDicts + 18 enums; append-only `FlightLog`/`InvoiceLineItem`/`AgencyRecord` correctly omit `updated_at`/`version`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (51 methods incl. the `/_clock/set_current_utc` test-driving endpoint)
- `api_errors.py` — all 41 error IDs + HTTP map, registered via `set_error_http_status_map()`
- `assertions.py` — per-entity structural assertions + `assert_season_billed_invariant` / `assert_filled_count_invariant`
- `factories.py`, `constants.py` (570 min default, 80 tenths limit, 840 min crew day, 60 min rest, 30.0 SLA, 0.98/0.05 penalty, tolerance 1)
- `test_users.py` — 7 role headers; `make_pilot_headers(crew_member_id)` mandatory builder for the entity-backed Pilot role
- `fixtures.py` — composite chains: carded aircraft/pilot workspace, OCC-threaded order/assignment/invoice creation, launch→arrive, sortie logging, retardant load lifecycle, submitted-invoice flow
- `__init__.py` barrel export

`test_suite/` (Stage 2): `conftest.py` + 8 files: `test_01_contracts_and_envelope.py`, `test_02_fleet_crew_carding.py`, `test_03_availability.py`, `test_04_dispatch_assignments.py`, `test_05_flight_logs_fatigue.py`, `test_06_retardant_loads.py`, `test_07_invoices_reconciliation.py`, `test_08_security_rbac.py`

**Test counts**
- Queue A (Difficulty): 36 tests — all 18 instances × exactly 2
- Queue B (Corner): 44 tests — 44 of 45 non-stub instances × 1; 7 `excluded_because` stubs not translated (all cross-references verified to resolve)
- Total: 80 tests; pytest collection clean

**Skipped instances (1)**
- `Corner/entities/aircraft_create_system_field_input_ignored` — PRD never states whether a client-supplied system field (`carding_status`) in a create body is ignored or rejected; two PRD-only readers diverge (201+UNCARDED vs 400), so the asserted outcome is not uniquely derivable. Gap left as gap.

**Tag/citation audit** (scripted): every one of the 80 tests ends with exactly one `Design: Difficulty/...` or `Design: Corner/...` line resolving to a real non-stub instance; zero dual/untagged/dangling tags. Every docstring quote was verified whitespace-normalized-verbatim against `PRD.md` (0 non-verbatim quotes after fixing ellipsis-splices, §2.9 `**Request shape**` bold markers, and §4 table rows to literal pipe format). Version assertions are relative (+1 increments per PRD §2.4/§3.1) since the PRD never pins the initial version value; system-stamped instants are compared as parsed datetimes against the PRD's pinned default clock (`2026-08-01T00:00:00Z`) rather than exact strings to stay format-agnostic.

## Step 6: Generate implementation — 2026-08-14T15:41:35.914Z

Done. Summary of the implementation for task_1756_aerial_firefighting_contract_operations.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1756_aerial_firefighting_contract_operations/workspace/implementation/`):
- `start.sh` — executable launcher; guards `pip install` behind `python3 -c "import flask"` so per-test reboots don't re-install; `exec python3 app.py` in the foreground.
- `requirements.txt` — `flask>=3.0`.
- `app.py` — Flask entry point; binds `0.0.0.0` on `$PORT` (default 10000); registers the blueprint and `ApiError`/404/405/500 handlers producing the PRD error envelope.
- `db.py` — in-memory stores (14 dicts, empty at boot, nothing seeded), logical clock defaulting to `2026-08-01T00:00:00Z`, UUID minting, millisecond timestamps, and a monotonic `_seq` for deterministic `created_at`-tie ordering.
- `errors.py` — full error-ID catalog verbatim from PRD §5 with HTTP statuses.
- `response.py` — success/error envelope exactly per PRD §2.2 (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more`).
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, declared-role set, endpoint role lists (priorities 1-2).
- `helpers.py` — strict request-shape parsing (strings, ints, enums, `YYYY-MM-DD` dates, ISO-8601 UTC datetimes) feeding `ERR_INVALID_REQUEST`.
- `services.py` — all business logic: calculations, cascades, serializers.
- `routes.py` — all 66 endpoint handlers.

**Endpoint count:** 66 implemented, matching PRD §4 exactly (I initially planned for 64 — the scaffold/PRD actually define 66).

**State machines implemented (9):** Contract (DRAFT/ACTIVE/SUSPENDED/CLOSED with the suspend-resume cycle and open-orders close guard), Aircraft (UNCARDED/CARDED/SUSPENDED/DECARDED), CrewMember duty dimension (AVAILABLE/FATIGUE_HOLD) evolving parallel to its carding dimension, CardingInspection (SCHEDULED/COMPLETED plus the FAILED-reschedule loop), AvailabilityPeriod (OFFERED/CONFIRMED/EXCUSED/UNAVAILABLE), Incident (REPORTED/ACTIVE/CONTAINED/CLOSED), DispatchOrder (PLACED/ACCEPTED/PARTIALLY_FILLED/FILLED/DECLINED/CANCELLED/CLOSED with derived fill-band bubble-up and demobilize auto-close), Assignment (ASSIGNED/EN_ROUTE/ON_INCIDENT/RELEASED/DEMOBILIZED), RetardantLoad (REQUESTED/LOADED/DROPPED), Invoice (DRAFT/SUBMITTED/DISPUTED/RECONCILED/PAID/VOID including the dispute-resubmit loop).

**Calculations implemented (8):** `availability_charge` (CWN flat vs exclusive-use threshold/prorate), `flight_sortie_billing` (pinned per-sortie round-half-up then sum), `invoice_net_composition` (pinned six-step order with exact-rational 98% compliance test), `crew_duty_projection` (chronological flown vs forward-looking projected, 80-tenths limit, 840-minute duty-day span), `reconciliation_billing` (agency basis on match, ±1-tenth tolerance, mismatch → DISPUTED with `RECONCILIATION_MISMATCH`), `reload_turn_time` (previous-drop tie-break by created_at, 30.0-minute SLA strict-greater), `season_billed_invariant` (submit/void/reconcile ledger compensation), `filled_count_invariant` (derived order band).

**Cascades:** the 3-link aircraft carding-failure cascade (inspection → aircraft SUSPENDED → CONFIRMED periods → UNAVAILABLE with CARDING reason → covering DRAFT invoices re-derived) and the 4-link fatigue cascade (FlightLog → CrewDutyDay ≥ 80 → CrewMember FATIGUE_HOLD → ASSIGNED assignments RELEASED/FATIGUE → order fill-band recompute), each touched entity taking its own `version` increment.

**Boot smoke test:** confirmed clean — fresh process via `bash start.sh` binds 0.0.0.0:$PORT, serves HTTP within ~2 s, returns the correct envelope with an empty store (`total_count: 0`), and shuts down cleanly releasing the port. Two end-to-end smoke suites passed covering exclusive-use + CWN flows, prorating, the pinned sortie rounding example from the PRD (1.05 h + 0.65 h → 330000 + 210000), penalty computation, billing-period closure, reconcile agency-basis switch with season-ledger delta, fatigue cascade, rest-release gating, and the OCC stale-version path. One bug found and fixed during smoke: assignment creation on a FILLED order now returns `ERR_DISPATCH_ALREADY_FILLED` (not `ERR_INVALID_STATE`) by checking fill before the accepting-state gate.

## Step 7: Run tests and iterate — 2026-08-14T16:00:32.336Z

All 8 rounds pass 80/80. Clean sweep achieved — exiting with the summary.

## Summary

**Iterations run:** 2 (iteration 1: 62/80 in all 8 rounds — 18 deterministic failures, zero flaky divergence; iteration 2: 80/80 in all 8 rounds).

**Tests deleted:** none. Every failing test traced to a PRD-verbatim rule; no PRD-silence or unique-derivability collapses required deletion.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1756_aerial_firefighting_contract_operations/test_helpers/fixtures.py` — `place_order` accepted `aircraft_quantity` but never forwarded it into `create_dispatch_order_payload`, so every fixture-placed order had quantity 1 and quantity-2 tests died in setup with `ERR_DISPATCH_ALREADY_FILLED`. Forwarded the parameter (root cause of 9 failures across test_04/05/06 — the triage-hint case: many "independent" failures from one upstream fixture bug).

**Fixes applied to `test_suite/`:**
- `test_02_fleet_crew_carding.py` — added missing `INSPECTOR` import (NameError in `test_aircraft_suspend_then_recard_refreshes_validity` and `test_failed_inspection_reschedule_resets_result`).
- `test_02_fleet_crew_carding.py::test_failed_inspection_reschedule_resets_result` — replaced exact-string equality on `scheduled_for` with parsed-instant equality. PRD §3.2 pins the new instant's value but §2.6 pins only "ISO 8601 UTC", not the fractional-digit rendering; the lexical pin failed the two-reader test (a faithful implementation normalizing to `.000Z` represents the same instant). Instant-value assertion preserved at full strength.
- `test_04_dispatch_assignments.py` — added missing `card_aircraft` import (NameError in `test_fatigue_hold_beats_wrong_contract_on_assignment`).
- `test_07_invoices_reconciliation.py` — threaded the `api` fixture into `_setup_single_day_invoice(self, api)` (it referenced `api` out of scope; NameError in both dispute/resubmit tests).

**Fixes applied to `implementation/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1756_aerial_firefighting_contract_operations/workspace/implementation/routes.py` + `services.py` (11 creation sites) — entities now born with `version: 1` instead of `0`. PRD §2.4 declares `version` increments by exactly 1 per mutation; the benchmark-wide helper `_assert_common_fields` (identical across tasks sharing this PRD boilerplate, and matching reference implementations) requires birth version ≥ 1. All suite version assertions are relative (`v0+1`), so nothing else shifted.
- `routes.py::create_assignment` — pass `planned_start` as a datetime (not the `fmt_dt` string) into `create_duty_day`. The string was later subtracted from a datetime in the 840-minute span check on any second same-day assignment, raising TypeError → 500 (surfaced as `ERR_INVALID_REQUEST`), which masked the rest-gap verdicts in both `TestPilotRestGap` tests.

Orchestrator verification: all 8 `results.{1..8}.json` confirmed `passed=80 total=80`.

## Step 8: Finalize PRD — 2026-08-14T16:05:19.251Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1756_aerial_firefighting_contract_operations/workspace/PRD_FINALIZED.md` written with exactly two inline edits, both traced to step_7_diff items.

**Line counts:** PRD.md 320 lines vs PRD_FINALIZED.md 320 lines (0.0% line delta — both edits are within-line insertions; ~190 characters added total).

**Changes:**
- §2.4 — revise — `version` now pinned as "an integer that **is 1 at creation** and increments by exactly 1 on every mutation" (previously the birth value was unpinned) — impl: `routes.py:173,311,393,508,624,722,806,1010,1282,1379` + `services.py:93` (11 creation sites, all `"version": 1`), mutation via `services.py:50` `touch()`.
- §2.6 — insert — new sentence pinning the canonical instant rendering: "Every instant the server emits is rendered in one canonical form — `YYYY-MM-DDTHH:MM:SS.sssZ`, UTC with exactly three fractional digits and any finer precision truncated to milliseconds — whether the instant was system-stamped by the server or supplied by the client and echoed back." — impl: `helpers.py:116-119` `fmt_dt` (the single serialization funnel for all business instants), `db.py:45-52` `iso_now_ms`, `response.py:14-16` `_ts`.

**Step 7 items requiring no edit:** the `fixtures.py` `place_order` forwarding, the INSPECTOR/`card_aircraft` imports, and the test_07 `api` fixture threading were pure test/fixture bugs; the `create_assignment` planned_start datetime fix was an implementation bug brought into line with PRD §3.5's already-unambiguous span prose.

**Per-edit pre-edit search log:**

Edit 1 (birth version):
- (a) Subject: initial value of `version` at entity creation.
- (b) Enumerated: all `"version"` assignments via grep — 11 creation sites (listed above) all set 1; sole mutation path `touch()` (`services.py:50`) increments by exactly 1; OCC reads (`routes.py:929,1356`) only compare; FlightLog/InvoiceLineItem/AgencyRecord creation sites (`routes.py:1218,1585`; `services.py:257,305,378`) carry no `version`, matching the existing §2.4 exception sentence, which was left verbatim.
- (c) No adjustment needed; "1 at creation" holds on every enumerated path including the auto-created CrewDutyDay.

Edit 2 (instant rendering):
- (a) Subject: canonical serialization format of instant-typed values in responses.
- (b) Enumerated via grep for `fmt_dt`/`iso_now_ms`/`iso_clock_ms`/`isoformat`/`strftime`: every business instant funnels through `fmt_dt` (serializers in `services.py:493-544`; stored stamps at `routes.py:1017,1090,1105,1122,1143,1432,1466,1609` and `services.py:443`), all producing `...SS.mmmZ` with `microsecond // 1000` truncation; `created_at`/`updated_at` via `db.iso_now_ms` and `api_request_timestamp` via `response._ts` use the identical form (consistent with §2.2/§2.4's existing three-fractional-digit pins); date-typed fields (`service_date`, `carded_until`, `period_*`, etc.) use `date.isoformat()` and are untouched by the instant-scoped sentence.
- (c) Adjustment made: draft wording said "system-stamped from the logical clock", but `created_at`/`updated_at` are wall-clock metadata stamps (§2.7's clock-read list deliberately excludes them), so the provenance clause was widened to "system-stamped by the server" — the sentence now makes a true universal claim about rendering only, without asserting a clock source for fields §2.7 does not govern.

## Step 9: Complete PRD — 2026-08-14T16:21:57.489Z

Done. All 21 edits applied cleanly (22 diff hunks: 21 single-line revisions + 1 two-line insertion).

## Summary

**Source:** `PRD_FINALIZED.md` (320 lines / 53,171 chars) → **`/home/ubuntu/github/CodingPRD/tasks/task_1756_aerial_firefighting_contract_operations/workspace/PRD_COMPLETED.md`** (322 lines / 55,921 chars). Delta: +2 lines, +2,750 chars.

**Counts:** 22 ambiguity-pins, 8 mismatch-revisions (30 behavioral pins across 21 edits).

### Changes

- **§2.2** — insert — ambiguity — unrouted paths / wrong methods answered in the error envelope with `ERR_INVALID_REQUEST` at the framework's 404/405 status — `implementation/app.py:19-29`
- **§2.3** — revise — ambiguity — non-integer limit/offset, limit outside 1–100, negative offset → `ERR_INVALID_REQUEST` — `implementation/routes.py:49-60`
- **§2.3** — revise — ambiguity — `created_at` sort ties break by creation order — `implementation/routes.py:62`, `implementation/db.py:31-42`
- **§2.3** — revise — ambiguity — `has_more` true exactly when `offset` + returned items < `total_count` — `implementation/response.py:43`
- **§2.4** — insert — ambiguity — CrewDutyDay derived totals (`flown_tenths`/`projected_tenths`) refresh in place without `updated_at`/`version` changes — `implementation/services.py:105-123` (no `touch` on duty days anywhere)
- **§2.6** — insert — ambiguity — whole-minute derivations (`available_minutes`, `reload_turn_minutes`) discard sub-minute remainder — `implementation/routes.py:617`, `implementation/services.py:206`
- **§2.8** — revise — mismatch — `expected_contract_version` is optional; omitted → no OCC check — `implementation/routes.py:1349-1357`
- **§2.8** — revise — mismatch — `expected_dispatch_order_version` under the same optional-when-present rule — `implementation/routes.py:920-930`
- **§2.9** — revise — mismatch — on reconcile, invoice state is validated before the segregation-of-duties comparison — `implementation/routes.py:1475-1480`
- **§3.1** — revise — mismatch — `contract_number` recorded as given, no uniqueness check — `implementation/routes.py:141-190`
- **§3.2** — revise — mismatch — `tail_number` uniqueness not enforced — `implementation/routes.py:295-321`
- **§3.2** — revise — ambiguity — `PASSED` against an already-`CARDED` subject is a no-op — `implementation/routes.py:547-553`
- **§3.2** — revise — ambiguity — `FAILED` against an `UNCARDED` subject is a no-op — `implementation/routes.py:561-564`
- **§3.2** — revise — ambiguity — decarding from `SUSPENDED` → `ERR_INVALID_STATE` — `implementation/routes.py:349-350`
- **§3.3** — revise — ambiguity — availability period takes the path contract as `contract_id`; aircraft's own contract affiliation unchecked — `implementation/routes.py:599-615`
- **§3.3** — revise — ambiguity — `available_minutes` = window length in whole minutes, sub-minute remainder discarded — `implementation/routes.py:617`
- **§3.4** — revise — mismatch — `incident_number` uniqueness not enforced — `implementation/routes.py:708-732`
- **§3.4** — revise — mismatch — `order_number` uniqueness not enforced — `implementation/routes.py:775-820`
- **§3.5** — revise — ambiguity — assignment creation against a `PLACED` (not-yet-accepted) order → `ERR_INVALID_STATE` — `implementation/routes.py:937-938`
- **§3.6** — revise — ambiguity — launch with non-`CARDED` aircraft → `ERR_AIRCRAFT_NOT_CARDED` (expired card separately → `ERR_CARDING_EXPIRED`) — `implementation/routes.py:1081-1085`
- **§3.6** — revise — ambiguity — rest-release when not on hold or latest duty day not strictly past → `ERR_INVALID_STATE` — `implementation/routes.py:466-473`
- **§3.7** — revise — ambiguity — `reload_turn_minutes` is whole-minute floor of the loaded−dropped difference — `implementation/services.py:206`
- **§3.8** — revise — mismatch — new invoice generates lines and computes totals immediately at creation (zeros only when no billable sources yet), rather than "all zero" unconditionally — `implementation/routes.py:1396`
- **§3.8** — revise — ambiguity — penalty line's `reference_date` is the invoice's `period_end` — `implementation/services.py:382`
- **§3.8** — revise — ambiguity — `agency_qty` populated only on flight lines; availability/penalty lines keep it null forever — `implementation/routes.py:1508-1514`
- **§3.8** — revise — ambiguity — availability-day line ordering ties break by the period's `created_at` ascending — `implementation/services.py:252`
- **§3.8** — revise — ambiguity — penalty line emitted only when `penalty_cents` is positive — `implementation/services.py:377`
- **§3.8** — revise — ambiguity — draft re-derivation triggers include availability posting, not just confirm/excuse/cascade/log — `implementation/routes.py:638`
- **§3.8** — revise — ambiguity — reconcile record match scoped to the invoice's contract; earliest-created record wins on multiple matches — `implementation/routes.py:1488-1495`
- **§3.8** — revise — ambiguity — on reconciliation mismatch, computed line-level agency values are retained while the invoice drops to `DISPUTED` — `implementation/routes.py:1516-1520`

Notable judgment calls: the four "unique identifier" claims (contract/aircraft/incident/order numbers) were revised because the implementation enforces no uniqueness anywhere and the error catalogue has no duplicate error; the two OCC fields were revised from "requires" to optional-when-present (impl skips the check when the field is absent); the §2.9 precedence list was amended at step 5 because reconcile validates state before SoD in `routes.py`. Tests were consulted only to confirm corners (e.g., the "all zero" invoice test uses an empty period, consistent with the revised wording).

## Pipeline complete

All Steps 1–9 finished. `workspace/PRD_COMPLETED.md` exists. Final state: 80/80 tests passing across all 8 stability-sweep rounds under `--isolation per-test-server`.
