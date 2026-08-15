## Step 2: Generate Scaffold — 2026-08-15T05:03:31.255Z

All checks pass. Scaffold generation is complete for task 1975.

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1975_fireworks_display_permitting_show/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (fixed response envelope verbatim; no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design:`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design:`

**Verdict block (verbatim from scaffold_lint.py):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(820 structured calls scanned across both design files; 3 initial FK-reverse-reachability violations fixed by adding `GET /pyro/displays`, `GET /pyro/permit-applications`, `GET /pyro/magazines` filtered lists.)

**Summary counts:**
- Entities: **13** (Operator, CrewMember, DisplayEvent, SitePlan, PermitApplication, Magazine, ProductBatch, InventoryMovement, WeatherReading, SecurityPost, MisfireRecord, SweepRecord, IncidentReport)
- State machines: **8** — three cyclic (DisplayEvent revision loop, PermitApplication INFO_REQUESTED↔SUBMITTED, ProductBatch CHECKED_OUT↔IN_MAGAZINE) plus a parallel weather_decision dimension on DisplayEvent
- Endpoints: **49** (12 are lint-mandated FK reverse-reachability GETs; includes `POST /pyro/_clock/set_current_utc` with the mandatory 2026-08-01T00:00:00Z default)
- Error catalog: **29** codes
- Roles: **4** (SystemAdmin opaque, Operator entity-backed, FireMarshal opaque, CrewMember entity-backed) with segregation-of-duties gates (approving marshal ≠ standby confirmer; incident reporter ≠ closer)
- §1.8 difficulty instances: **19** (≥2 per rule; combinatorial_formula has 3, one each for modes a/b/c — wind-adjusted fallout branch formula, standby-fee per-line rounding pin, allocation-vs-RSD circular gate)
- §1.9 corner instances: **51 active + 13 excluded_because stubs** = 64 entries; 83 instance names unique across the union

**Difficulty highlights:** 2 OCC concurrency rules on DisplayEvent.version (site-plan supersede, go-no-go); depth-3 operator-suspension cascade (suspend → event cancel → auto-RETURN → magazine mass recompute) and depth-2 dud-halt cascade (misfire → dud_count → threshold → SHOW_COMPLETE/DUD_HALT); two compensating invariants (magazine NEW lbs; batch unit partition); boundary pins at wind 20.0 (strict <), capacity exact-fit (inclusive <=), soak 15:00 (inclusive), weather age 30:00 (inclusive), venue buffer +120 min (half-open), license expiry (closed containment); all formula-derived asserts pre-computed to literals (e.g. provisional 98500 vs final 107683/137683/105750, fallout 350/420/504/462, guards ceil rules).
## Step 3: Copy INSTRUCTION.md — 2026-08-15T05:03:50.165Z

Copied ./INSTRUCTION.md to tasks/task_1975_fireworks_display_permitting_show/workspace/INSTRUCTION.md (1424 bytes).
## Step 4: Generate PRD — 2026-08-15T05:09:21.307Z

PRD generation complete. Final summary:

**Output**: `workspace/PRD.md` — 281 lines.

**Section list**:
- §1 Introduction (3 paragraphs, business-context angle)
- §2 Global Specifications & System-Wide Principles — 2.1 RBAC, 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination, 2.4 Common Resource Properties and the Logical Clock, 2.5 Licensing/Certification/Inspection Windows, 2.6 Precision/Rounding/Monetary Conventions, 2.7 Optimistic Concurrency Control, 2.8 Validation Ordering, 2.9 Nested Resource Retrieval and Aggregate Consistency
- §3 Business Logic & Workflows — 3.1 Onboarding Operators/Crew/Storage, 3.2 Booking a Display and Filing the Site Plan, 3.3 The Permit Review Loop, 3.4 Inventory (Magazines/Batches/Movements), 3.5 Perimeter Security and Show-Day Readiness, 3.6 Weather and the Go/No-Go Decision, 3.7 Firing/Misfires/Cancellation Cascade, 3.8 Sweeps/Incidents/Show Close-Out
- §4 Endpoint Definitions (49-row table, 4 columns)
- §5 Error Code Catalogue (29 rows, 2 columns)

**Hard-contract audit results**:
- Contract 1 (Field-Name Coverage): entities 99/99, request_body 72/72, query_params 8/8, path_params 1/1 — **PASS** (one repair: added `magazine_id` to §3.4 after first pass).
- Contract 2 (Rule Coverage): both OCC rules expressed with `write_endpoint` + `occ_field` + `ERR_STALE_VERSION`/412 and no race framing; all 8 state machines' transitions/states/enum values present; all 9 calculations with constants (70 ft/in, 8 mph threshold, 0.05/mph factor, 1.5 cap, 25000/14500/30000 cents, 100-ft guard spacing, dud floor 2 / 5-percent rate, 30-min weather validity, 60-min decision window, 20.0/25.0 wind limits) expressed in precise prose; all 29 error IDs mentioned in §2/§3; the pinned subtleties are explicit (duplicate-application evaluated before generic state check on application creation, final-fee minute-proration with the ceil-hours alternative expressly forbidden, `fired_count` evaluated before the misfire, exact-fit capacity inclusive, 30:00-minutes-old-is-fresh inclusive boundary, both decision-window bounds inclusive, quarantined stock still counted in magazine mass, checkout-then-return bit-identical invariant, allocation-RSD pinned evaluation order) — **PASS**.
- Contract 3 (§3 Path Purity): 429 backticked tokens scanned in §3, 0 path tokens, 0 bare-method tokens, 0 method+path combos — **PASS**.

Note on tooling: an initial audit run via bash heredoc silently mangled the backtick character class in the regex, producing false-missing results; re-running the audit from a written script file (`/tmp/audit_1975.py`, `/tmp/audit2_1975.py`) gave correct results.
## Step 5: Generate Unit Tests — 2026-08-15T05:32:45.139Z

Everything checks out. Final state:

- **93 tests collected**, all compiling, all importing against the real framework.
- **36 difficulty-queue tests** covering 18 of 19 §1.8 instances (exactly 2 each).
- **57 corner-queue tests** covering all 51 non-stub §1.9 instances (each ≥1; six instances covered by 2 tests where the design recipe had two distinct trigger legs — staleness/window/soak boundaries, OCC stale+fresh, auto-close blocked+unblocked).
- **11 `excluded_because` stubs** correctly not translated (cross-references all resolve to real difficulty instances).
- **Zero strays** — every tag resolves to a real instance.
- **Every docstring**: verbatim PRD quote (audit passed — all citations survive literal grep of PRD.md) + `Design:` tag as the last line.

**Skip (1 instance):** `Difficulty/priority_pair_validation_conflict/state_beats_safety_on_quarantined_movement` — PRD-first filter failure. The recipe's trigger (CHECK_OUT against a CANCELLED event on a QUARANTINED batch) trips two priority-7 candidates simultaneously: `ERR_INVALID_STATE` (event terminal) and `ERR_PERMIT_NOT_APPROVED` (the event's application was WITHDRAWN by the cancellation cascade, so the permit is not approved). PRD §2.8 pins the tier ladder and the duplicate-vs-state ordering only for permit creation; it says nothing about intra-tier-7 ordering between these two errors. Two faithful PRD-only implementers could ship different answers, so the asserted `ERR_INVALID_STATE` outcome is not uniquely derivable. Per the Core rule the instance was skipped rather than weakened; no placeholder emitted.

**Helper files written** (all under `test_helpers/`):
- `__init__.py` — barrel export (framework + PRD-specific)
- `types.py` — 13 entity TypedDicts (append-only `InventoryMovement`/`WeatherReading` correctly omit `updated_at`/`version` per PRD §2.4) + 20 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per each of the 46 PRD endpoints
- `api_errors.py` — 29 `ApiErrorId` members + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + `assert_batch_unit_accountability` invariant
- `factories.py` — payload factories for all input-bearing endpoints
- `constants.py` — all calculation thresholds (70 ft/in, 8/0.05/1.5 wind, 25000/14500/30000 fees, 100 ft guards, 2/0.05 dud halt, 30/60-min windows, 20/25 wind limits, 15-min soak, 120-min venue buffer)
- `test_users.py` — `TEST_USERS` shared constants for opaque roles + mandatory per-instance builders `make_operator_headers`/`make_crew_member_headers` for entity-backed roles (identity threading per §1.7)
- `fixtures.py` — composite fixtures across all 5 tiers: `create_operator`, `set_clock`, event progression (`setup_event_draft` → `_submitted` → `_approved` → `_standby_confirmed` → `_ready` → `_in_progress` → `_show_complete` → `_closed`), hierarchy helpers (`create_magazine_with_batch`, `add_lead_crew`, `add_secured_post`, `checkout_product`), `go_decision`

**Test files** (under `test_suite/`): `conftest.py` + `test_01_envelope_and_creation.py` (11), `test_02_auth_rbac_scope.py` (8), `test_03_permits_and_site_plans.py` (16), `test_04_inventory_movements.py` (19), `test_05_readiness_gates.py` (6), `test_06_weather_go_no_go.py` (14), `test_07_show_firing_misfires.py` (8), `test_08_sweep_close_fees.py` (7), `test_09_cascades.py` (4).

(Note: the first Step 5 subagent invocation exited after producing only a plan without writing files; it was resumed via message and completed the full generation.)
## Step 6: Generate Implementation — 2026-08-15T05:41:21.325Z

Implementation complete for task_1975 (Fireworks Display Permitting & Show Operations).

**Files written** (all under `workspace/implementation/`):
- `start.sh` — executable launcher; guarded `pip install` (no-op once flask is importable), `exec python3 app.py` in foreground
- `requirements.txt` — flask only
- `app.py` — Flask entry point, error handlers, per-request lock, binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory store (13 entity dicts), logical clock starting exactly at `2026-08-01T00:00:00Z`, no seed data
- `errors.py` — all 29 error IDs with their exact HTTP statuses
- `response.py` — envelope helpers (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more`), serialization (ISO-8601 3-fractional-digit UTC timestamps, Decimal→number), `created_at` ASC ordering with insertion-sequence tiebreak
- `validation.py` — tier-3 schema validation (required/conditional fields, types, enums, unknown-field rejection, ERR_INVALID_QUANTITY for non-positive counts), pagination parsing (limit default 10, min 1, max 100)
- `auth.py` — `X-User-ID`/`X-User-Role` authentication and role gating
- `services.py` — all calculation rules and cascades
- `routes_operators.py`, `routes_displays.py`, `routes_permits.py`, `routes_inventory.py`, `routes_ops.py`

**Endpoints:** all 49 routes from the §1.5 endpoint table implemented (the "46" in the complexity note undercounts; the table lists 49).

**Notable design decisions:**
- **Validation ladder** follows PRD §2.8 tier order strictly (auth → role → schema → existence → ownership → OCC → state → safety → scope → temporal → capacity), including the permit-create override (ERR_DUPLICATE_APPLICATION before generic state check) and tier 8 weather-limits before tier 10 stale/window checks on go-no-go.
- **OCC** (`expected_display_event_version`) only on site-plan create and go-no-go; event version bumps only where the scaffold explicitly declares them (movements and weather readings do not bump event version).
- **Venue conflict** implemented symmetrically: each booking window carries its own 120-minute trailing buffer, inclusive overlap — the literal one-sided reading produces order-dependent results incompatible with the buffer's purpose.
- **Final standby fee** uses minute-prorated actuals with per-line round-half-up (verified: 90 elapsed minutes → 106750 cents vs 114000 provisional).
- **Dud auto-halt** verified at threshold 2 (floor) and scaling with fired_count; misfire log + auto-halt each bump event version.
- **Cancellation cascade** (manual cancel, NO_GO, operator suspension) shares one code path: posts → RELEASED, non-terminal applications → WITHDRAWN, auto-generated RETURN movements (`recorded_by_user_id: "system"`) restore magazine mass bit-identically.
- Verified via 5 live test suites (~150 assertions) covering the full happy path, wind-adjustment math (full/half/no sector), freshness/window boundary inclusivity, SoD on standby-confirm and incident close, quarantine, capacity exact-fit, pagination, envelope shape, and `bash start.sh` boot/reboot (fast, guarded install).
## Step 7: Test Iteration (8-round stability sweeps) — 2026-08-15T05:55:00.000Z

Iteration 1 sweep: 8/8 rounds at 91/93; union of failures = 2 tests, both
deterministic (failed all 8 rounds):
- `test_venue_buffer_exact_edge_accepted` (got 409 ERR_VENUE_CONFLICT, expected 201)
- `test_wind_19_9_accepted` (got 422 ERR_FALLOUT_EXCEEDS_BOUNDARY, expected 200)

Diagnosis (STEP 1–3):
1. Venue buffer — PRD §3.2 verbatim-covers the rule ("overlaps this event's
   window extended by a 120-minute trailing buffer"). Unique derivability holds:
   the PRD marks every inclusive boundary explicitly elsewhere ("inclusive at
   both ends", "both bounds inclusive", "an exact fit allowed"), the venue
   sentence carries no inclusivity marker, and an inclusive reading would
   absurdly forbid even zero-buffer back-to-back bookings (new_start ==
   old_end). Strict (positive-span) symmetric overlap is the faithful reading.
   Test faithful → implementation bug. Fixed
   `implementation/services.py::venue_conflict`: inclusive `<=` comparisons
   replaced with strict `<` on both window ends.
2. Wind 19.9 — the wind-limit rule is PRD-covered, but the test's own setup
   (boundary 300, arc center 0°, wind direction 180° → delta 0 full factor;
   wind 19.9 → factor capped 1.5; base 280 → adjusted 420 > 300) forces the
   ERR_FALLOUT_EXCEEDS_BOUNDARY rejection that PRD §3.6 mandates ("it must not
   exceed the CURRENT plan's spectator_boundary_ft"). Test setup bug, not an
   implementation bug. Fixed `test_suite/test_06_weather_go_no_go.py::
   test_wind_19_9_accepted`: setup now passes
   `site_plan_overrides={"spectator_boundary_ft": 700}` so the fallout gate
   clears and the wind-limit rule alone decides the outcome. Assertion
   unchanged.

No tests deleted; no test_helpers changes.

Iteration 2 sweep: 8/8 rounds at 93/93 — stable, done.

**Step 7 final summary (orchestrator-recorded):**
- Iterations run: 2 (each a full 8-round parallel sweep, 93 tests/round, per-test-server isolation).
- Result: all 8 rounds pass 93/93 — clean exit (verified by orchestrator against results.1..8.json).
- Tests deleted: none.
- Fixes applied to `test_suite/`: `test_06_weather_go_no_go.py::test_wind_19_9_accepted` — test-setup bug (boundary 300 + downwind full factor forced PRD-mandated ERR_FALLOUT_EXCEEDS_BOUNDARY before the wind-limit rule could decide); setup now uses `spectator_boundary_ft: 700`, assertion unchanged.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `implementation/`: `services.py::venue_conflict` — inclusive `<=` overlap comparisons changed to strict `<` (PRD §3.2 uniquely determines positive-span overlap; PRD marks every inclusive boundary explicitly elsewhere and the venue sentence carries no such marker).
## Step 8: Finalize PRD — 2026-08-15T05:58:30.000Z

Done. `PRD_FINALIZED.md` is written with exactly one revision.

**Line counts:** PRD.md 281 lines, PRD_FINALIZED.md 281 lines — 0% line-count delta (one line revised in place; +481 characters on that line).

**Changes (one total):**
- §3.2 (Booking a Display and Filing the Site Plan) — revise — the venue booking-buffer sentence now pins (1) symmetric buffering (every event's window, new and existing alike, is extended by its own 120-minute trailing buffer beyond `scheduled_end_at`) and (2) strict positive-span overlap (windows merely touching at one instant, e.g. a start exactly at the other window's buffered end, do not conflict). The old wording ("this event's window extended by a 120-minute trailing buffer") was one-sided and strictness-ambiguous — `impl: services.py:276-290` (`venue_conflict`: `ev.start < new.end + buf AND new.start < ev.end + buf`, both strict), sole caller `routes_displays.py:63`.

**Step 7 test-suite item (no edit made):** `test_06_weather_go_no_go.py::test_wind_19_9_accepted` was verified to be a pure test-setup bug. Implementation §3.6 behavior (`services.py:125-141` `wind_adjusted_radius`, `routes_displays.py:261-271`) matches PRD §3.6 verbatim: strict-below 8-mph drift threshold, factor `1 + (wind − 8) × 0.05` capped at 1.5 unrounded, delta bands ≤45 / ≤135 / >135, round-half-up integer feet, rejection iff final radius strictly exceeds `spectator_boundary_ft`. PRD already uniquely determines this; no edit.

**Per-edit pre-edit search log**

Edit 1 — §3.2 venue buffer sentence:
- (a) Subject: venue booking-buffer semantics — which events are compared, how each window is extended, overlap strictness, terminal-state exclusion, operator scoping, and invocation sites.
- (b) Impl paths enumerated and read/grepped: `services.py:276-290` (`venue_conflict` definition — symmetric buffer via `new_end_buffered` and `ev["scheduled_end_at"] + buf`, strict `<` both sides, skips `EVENT_TERMINAL = {"CLOSED","DENIED","CANCELLED"}` at `services.py:28`, `operator_uid` parameter unused → no operator scoping); `routes_displays.py:40-86` (sole caller at display creation, ordered after the license-window check, matching §2.8 tier-10 order); global grep for `venue_conflict|VENUE_BUFFER|ERR_VENUE_CONFLICT` (no other callers); global grep for `scheduled_start_at|scheduled_end_at` writes (only `routes_displays.py:69-70` — no reschedule/revise-window endpoint exists, so creation is the only gate site); `services.py:223-234` `cancel_event` and `routes_operators.py:83-85` suspension cascade plus `routes_permits.py` deny path (all land events in terminal states, hence excluded from future venue checks — consistent with the retained "non-terminal" qualifier); `test_suite/test_03_permits_and_site_plans.py:218-301` as auxiliary evidence (inside-buffer 409, exact-edge 201, cancelled-event ignored).
- (c) Wording adjustment: the symmetric implementation forbids pairs the PRD's one-sided reading would permit (a new event starting 1 minute after an existing event's end + under 120 min conflicts only under the symmetric reading — and the surviving test `test_venue_buffer_conflict_inside_buffer` exercises exactly that ordering), so the symmetric semantics were pinned explicitly rather than merely clarifying strictness. Kept "another non-terminal event" and "creation is rejected" unchanged to avoid new mismatches on operator scoping (impl has none) and invocation site (creation only); strictness expressed as "positive shared span" rather than a bare "strict `<`" to cover both window endpoints truthfully, matching the two-sided strict comparisons in code.
## Step 9: Complete PRD — 2026-08-15T06:17:18.785Z

Done. `PRD_COMPLETED.md` is produced as a minimal patch over `PRD_FINALIZED.md`.

**File stats**
- Source: `PRD_FINALIZED.md` — 281 lines, 44,489 chars. `PRD_COMPLETED.md` — 281 lines, 48,600 chars. Delta: +4,111 chars, 0 net line changes (29 lines revised in place; no new sections/paragraphs).

**Counts**: 32 ambiguity-pins, 1 mismatch-revision (33 logical changes across 29 edited lines).

**Changes** (section — insert|revise — ambiguity|mismatch — what changed — impl ref):
- §2.1 Operator bullet — insert — ambiguity — unknown operator `X-User-ID` on aggregate-creating endpoints (displays, magazines) fails as `ERR_NOT_FOUND` — routes_displays.py:58, routes_inventory.py:69
- §2.1 CrewMember bullet — revise — ambiguity — crew caller's own record must exist on recording/reporting writes (`ERR_NOT_FOUND`); crew reads never resolve the caller — routes_ops.py:37-41
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_VALIDATION`; list filters are exact-match, unmatched filter → empty list, never an error — validation.py:95-117
- §2.4 — insert — ambiguity — at creation `updated_at` equals `created_at` and `version` begins at 1 — db.py:38-45
- §2.4 — insert — ambiguity — clock-set accepts any instant (backward moves allowed); response `data` echoes `current_utc` — routes_operators.py:18-26
- §2.5 — insert — ambiguity — duplicate `atf_license_number` at registration → `ERR_VALIDATION` — routes_operators.py:39-41
- §2.5 — insert — ambiguity — suspension blocks writes/transitions; reads remain permitted — check_operator_active call sites (writes only)
- §2.6 — insert — ambiguity — supplied timestamps truncated (not rounded) to whole seconds at ingestion — validation.py:26
- §2.7 — insert — ambiguity — OCC comparison is exact equality; any mismatch (incl. future versions) → `ERR_STALE_VERSION` — routes_displays.py:139,241
- §2.8 — revise — ambiguity — `ERR_INVALID_QUANTITY` scope pinned to movement `quantity`, batch `quantity_units`, application `standby_engines` — routes_inventory.py:124-125,213-214; routes_permits.py:37-38
- §3.1 — insert — ambiguity — magazine list `operator_id` filter naming another operator → `ERR_FORBIDDEN_OWNERSHIP` — routes_inventory.py:98-100
- §3.2 — insert — ambiguity — displays list: Operator confined to own displays; foreign `operator_id` filter → `ERR_FORBIDDEN_OWNERSHIP` — routes_displays.py:102-105
- §3.2 — insert — ambiguity — site-plan filing is not gated on event status (any status, incl. terminal) — routes_displays.py:117-164
- §3.3 — insert — ambiguity — `standby_engines` < 1 → `ERR_INVALID_QUANTITY` — routes_permits.py:37-38
- §3.3 — insert — ambiguity — referenced plan need not itself be `CURRENT` at initial submission — routes_permits.py:42-58
- §3.3 — insert — ambiguity — global applications list: Operator sees only own; foreign `display_event_id` filter → `ERR_FORBIDDEN_OWNERSHIP` — routes_permits.py:107-121
- §3.3 — insert — ambiguity — resubmit with a plan both foreign and superseded → `ERR_SCOPE_MISMATCH` (foreign check first) — routes_permits.py:200-204
- §3.4 — insert — ambiguity — batch `quantity_units` ≤ 0 → `ERR_INVALID_QUANTITY` — routes_inventory.py:124-125
- §3.4 — insert — ambiguity — movement permit gate = event status in {APPROVED, STANDBY_CONFIRMED, READY, IN_PROGRESS, SHOW_COMPLETE, SWEEP_VERIFIED, CLOSED} (incl. terminal CLOSED) — services.py:32-33, routes_inventory.py:227-228
- §3.4 — insert — ambiguity — RETURN/EXPEND discard supplied manifest fields (stored as null) — routes_inventory.py:276-278
- §3.4 — insert — ambiguity — EXPEND's `fired_count` update does not increment the event's `version`/`updated_at` — routes_inventory.py:263-269 (no `bump(ev)`)
- §3.4 — insert — ambiguity — quarantine `reason` accepted but not persisted on the batch — routes_inventory.py:182-196
- §3.5 — insert — ambiguity — post creation: duplicate `post_label` → `ERR_VALIDATION`, no CURRENT plan → `ERR_VALIDATION`, radius shortfall → `ERR_FALLOUT_EXCEEDS_BOUNDARY`, not status-gated — routes_ops.py:124-137
- §3.5 — revise — ambiguity — standby-confirm: SoD check fires before engine-count comparison; `note` not persisted — routes_displays.py:192-196
- §3.5 — insert — ambiguity — ready gates evaluate certification → security → product — routes_displays.py:211-226
- §3.6 — revise — **mismatch** — decision-window and freshness gates apply to GO only; NO_GO accepted whenever READY (PRD prose had gated "the decision" on the window) — routes_displays.py:246-280
- §3.6 — insert — ambiguity — GO gate order pinned: weather limits (skipped only when no reading) → freshness → window → wind-adjusted radius/boundary — routes_displays.py:246-271
- §3.6 — insert — ambiguity — GO base radius is zero when no batch holds on-site product — routes_displays.py:262-264
- §3.6 — insert — ambiguity — manual-cancel `reason` accepted but not persisted — routes_displays.py:296-307
- §3.7 — insert — ambiguity — misfire logging has no event-state precondition; named batch must belong to event's operator (`ERR_SCOPE_MISMATCH`) — routes_ops.py:195-217
- §3.7 — insert — ambiguity — dud-halt auto-transition also stamps `show_completed_at` — routes_ops.py:237-241
- §3.8 — insert — ambiguity — sweep creation requires event `SHOW_COMPLETE`, else `ERR_INVALID_STATE` — routes_ops.py:313-314
- §3.8 — insert — ambiguity — sweep-verify `note` accepted but not persisted — routes_ops.py:351-364

Notable deliberate non-changes (impl behavior already uniquely pinned by existing PRD prose): the §2.8 validation ladder ordering (impl matches everywhere, including duplicate-before-state on application submission and manifest-compliance last), all calculation formulas (RSD, wind adjustment, guard spacing, fees, dud-halt threshold), the cancellation cascade, inclusive/exclusive boundary semantics, and the error catalogue.
