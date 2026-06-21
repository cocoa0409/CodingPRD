# Worklog — task_0444_banquet_event_order

Scenario: Banquet Event Order & Catering Sales (BEO): event inquiry & space hold, function-room & setup diagram, F&B menu (per-person/consumption), AV/labor/service-charge & gratuity, room-block linkage, guarantee count & overset, deposit & payment schedule, post-event actualization

Difficulty: Expert (§0.4 Expert band)

## Step 1: Create Task Directory — 2026-06-21T01:28:27.000Z

Directory `tasks/task_0444_banquet_event_order/` and its `workspace/` subdir were pre-assigned/reserved (auto-increment overridden to avoid ID contention with 4 sibling pipelines). Verified both exist and `workspace/` is empty. No new index allocated.

## Step 2: Generate Scaffold — 2026-06-21T01:56:00.000Z

All three scaffold files generated and verified. The scaffold-generator's own `scaffold_lint.py` returns `VERDICT: clean lint` across all three files (306 §1.8/§1.9 calls conform to §1.5; all 8 FKs reverse-reachable).

**Files written**
- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys) — 1105 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`) — 923 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`) — 1205 lines

**Complexity profile:** primary archetype temporal_windowing + secondary pricing_engine; hybrid topology; branching state-machine shape; peer_roles; immediate consistency.

**Scaffold contents (Expert band)**
- **Entities: 9** — FunctionRoom, HotelRoomBlock, Event (aggregate root, computed totals), FunctionRoomBooking, MenuLine, ServiceLine, RoomBlockLink (junction), PaymentScheduleItem, Payment (append-only).
- **State machines: 4** — Event (branching + DEFINITE↔TENTATIVE revision cycle, terminal COMPLETED/CANCELLED), FunctionRoomBooking (HOLD↔DEFINITE↔RELEASED cycle), RoomBlockLink (RESERVED→PICKED_UP→RELEASED), Payment (APPLIED→VOIDED).
- **Calculations: 9** — billable_count (overset/guarantee/actual dual-variant), menu_line_extended, effective_room_capacity, rooms_committed (reserved-vs-pickedup dual-variant), block_night_occupancy (half-open per-night aggregate capacity), room_rental (started-hour ceil), charge_rollup (pinned per-component round_half_up: service charge → tax, gratuity excluded; ESTIMATE/ACTUAL variants), payment_waterfall (sequence_no order), balance_due.
- **Validations: 13** (priority-ordered, 8 categories) | **Endpoints: 41** (incl. `/_clock/set_current_utc` test-driving endpoint, default 2026-01-01T00:00:00Z) | **Error catalog: 18** | **Roles: 4** (PlatformAdmin, SalesManager, BanquetCaptain, AccountingClerk — all opaque) | **Concurrency rules: 2** (both OCC on Event.version, 412).

**Difficulty design (§1.8): 18 instances** — exactly 2 per each of the 9 §0.5 rules. All formula-derived asserts pre-computed as literals.

**Corner design (§1.9): 42 instances** (38 active + 4 `excluded_because` stubs pointing at real §1.8 instances) spanning all 9 claim-extraction sections.

## Step 3: Copy Shared Files — 2026-06-21T01:56:34.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0444_banquet_event_order/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-21T02:02:21.000Z

Generated `workspace/PRD.md` — a 275-line prose PRD for the BEO domain.

**Sections covered:**
- §1 Introduction — catering-sales lifecycle, four roles, estimate/actual + cascade model.
- §2 Global Specifications — RBAC (2.1), response envelope (2.2), pagination (2.3), common properties/versioning (2.4), hierarchical/cascading consistency (2.5), money & round-half-up (2.6), OCC on guarded writes (2.7), nested validation ordering (2.8), logical clock (2.9).
- §3 Business Logic — 9 scattered workflow subsections: shared inventory, event open/hold, booking occupancy + buffered double-booking, setup-style capacity, headcount estimate/guarantee/actual, room-block per-night linkage, pricing & charge rollup, deposits/waterfall, void/cancel close-out.
- §4 Endpoint table — 41 endpoints.
- §5 Error catalogue — 18 error IDs.

**Hard Contracts (all PASS):** Contract 1 Field-Name Coverage 62/62; Contract 2 Rule Coverage all 16 high-risk categories; Contract 3 §3 Path Purity 0 violations. §2.2 verified byte-identical to canonical response-structure template.

**Confirmation:** Did NOT read/grep/reference SCAFFOLD_DIFFICULTY_DESIGN.yaml or SCAFFOLD_CORNER_DESIGN.yaml.

## Step 5: Generate Unit Tests — 2026-06-21T02:24:06.000Z

Generated complete test infrastructure from the two design indices, PRD-adjudicated.

**Test files: 5** (74 test functions total), all passing against the reference implementation under `--isolation per-test-server` (74 passed):
- `test_01_pricing_and_calculations.py` (10) — charge rollup estimate/actual variants, per-component rounding order, billable_count selection, menu/service extensions, room rental started-hour rounding, payment waterfall
- `test_02_state_machines_and_cascades.py` (14) — event revision loop, booking HOLD/DEFINITE cycle, cancel/actualize cascades, reserve→release and apply→void compensating invariants, state-machine rejections, terminal lockdown, derived-field reconciliation
- `test_03_constraints_and_overlap.py` (13) — make-definite validation priority pairs, buffered pairwise room overlap, per-night block aggregate capacity, capacity gate, cross-entity state/deposit gates, pricing-mode mismatch, pickup range
- `test_04_crud_rbac_and_concurrency.py` (19) — event defaults/computed zeros/not-found/required-field/enum/range, listing envelope, payment immutability, reverse-reachability listing, clock, RBAC denials, OCC stale-version guards, immediate-consistency cascade
- `test_05_difficulty_supplement.py` (18) — second-angle test for each difficulty instance

**Coverage (audited programmatically):** Queue A (Difficulty) all 18 instances covered by exactly 2 tests each (36 tests); Queue B (Corner) all 38 non-stub instances covered by ≥1 test (38 tests); 4 `excluded_because` stubs correctly NOT translated. Every test carries exactly one valid `Design:` tag; all 105 PRD citations verbatim.

**Instances skipped: 0** — every non-stub instance passed the PRD-first two-condition filter.

**test_helpers files produced (9):** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`. All four roles opaque per PRD §2.1 (shared role-constant headers + unknown-role header only). Payment TypedDict omits version/updated_at (append-only).

**One test bug found and fixed during validation:** DELETE menu-line test changed from `validate_success(...)` to direct `status_code == 204` assertion (PRD §4 specifies 204 No Content empty body).

## Step 6: Generate Implementation — 2026-06-21T02:24:06.000Z

Built complete Python + Flask implementation at `workspace/implementation/`.

**Files produced (10):** `start.sh` (foreground launcher, binds `0.0.0.0:$PORT` default 10000 via `exec python3 app.py`, flask-import-guarded pip install), `requirements.txt` (flask==3.0.3), `app.py` (entry + all 41 routes + error handlers + validation-priority ordering), `db.py` (in-memory dicts, logical clock default `2026-01-01T00:00:00Z`), `services.py` (all calculations using Decimal/ROUND_HALF_UP + serializers), `errors.py`, `response.py`, `middleware.py` (auth/RBAC), `validators.py`, `helpers.py`.

**Endpoint count: 41** (full PRD §4 table incl. clock, shared inventory, event lifecycle, bookings, menu/service lines, room-block links, payment-schedule items, payments).

**Storage & startup:** In-memory only (Python dicts in `db.py`); no SQLite, no file I/O, no persistence; every process start wipes all state. No seeding (verified fresh boot returns `total_count: 0`). `start.sh` binds `0.0.0.0` on `$PORT` foreground via `exec`.

**Key design decision flagged:** Per PRD §2.7, Event `version` (OCC token) is bumped ONLY by booking-create and payment-record. Lifecycle transitions and line edits refresh `updated_at` but do not bump `version` (required for difficulty test recipes capturing `ev_v0` then reusing it). Child/shared entities each bump their own version on mutation per §2.5.

Self-verified against ~40 scenarios from §1.8/§1.9 recipes — all pass.

## Step 7: Run Tests and Iterate — 2026-06-21T02:43:00.000Z

Done. Two consecutive clean 8-round parallel sweeps confirm the fix. (Orchestrator re-ran a third independent 8-round sweep to persist the final `results.{1..8}.json` artifacts — all 8 rounds 74/74, 0 failed.)

**Iterations run:** 2 sweeps after the diagnostic fix (plus the initial baseline sweep). The fix held on both — 16 consecutive parallel rounds at 74/74.

**Diagnosis.** The baseline sweep showed 4 of 8 rounds failing on a flaky union of 4 tests (`test_get_nonexistent_event_returns_not_found`, `test_lock_guarantee_succeeds_once_deposit_settled`, `test_create_event_missing_required_field_invalid_request`, `test_function_room_touching_endpoint_after_buffer_does_not_collide`). Reading each `results.${i}.json` failure detail showed every one was `status: "error"` with the message `"API server ... could not be restarted before <test>"` — i.e. pytest setup-phase boot-latency timeouts, NOT assertion or logic failures. The failing tests were scattered (not the first-in-file), and the same tests passed cleanly in other rounds. Root cause: under `--isolation per-test-server`, the runner reboots the server before every one of ~74 tests; with 8 rounds running concurrently (~8× CPU contention), some Werkzeug boots occasionally slipped past the runner's 15s readiness window. No test reached STEP 1 of the diagnostic protocol because no test asserted anything against the implementation — so no PRD coverage/derivability question arose, and no test was deletable.

**Tests deleted:** none. Every failure was an infrastructure boot timeout, not a PRD-fidelity or unique-derivability problem.

**Fixes applied to `test_helpers/`:** none. No fixture, factory, or role-header constructed a PRD-inconsistent precondition.

**Fixes applied to `implementation/`:**
- `workspace/implementation/start.sh` — Removed the per-restart `python3 -c "import flask"` probe that spawned an extra Python interpreter on *every* server reboot. Gated the one-time dependency install behind a sentinel file kept outside the implementation tree (in `$TMPDIR`, keyed to the Python prefix) so the impl dir stays write-free/state-free, and steady-state restarts `exec` straight into the app with zero probe-subprocess overhead — cutting per-boot latency on the critical path.
- `workspace/implementation/app.py` (`__main__` block) — Silenced the Werkzeug request logger (`logging.getLogger("werkzeug").setLevel(logging.ERROR)`) so each handled request skips the stderr access-log write, and pinned `debug=False, use_reloader=False` to keep the boot lean. (An earlier attempt to suppress the dev banner via `WERKZEUG_RUN_MAIN=true` broke the boot with a `WERKZEUG_SERVER_FD` KeyError and was reverted.)

No endpoints, fields, side effects, or storage behavior were changed; storage remains in-memory only and the API contract is untouched.

## Step 8: Finalize PRD — 2026-06-21T02:45:11.000Z

Produced `workspace/PRD_FINALIZED.md` — a verbatim copy of `PRD.md` with **zero behavioral edits** (byte-identical, confirmed via `diff`, exit 0). 275 lines / 275 lines, 0% delta.

**Changes:** No edits. Both Step 7 implementation fixes were confined to boot-latency and launcher mechanics and touch nothing the PRD describes:
- `start.sh` — sentinel-gated one-time dependency install + `exec python3 app.py`, replacing a per-restart `import flask` probe. Pure boot-latency optimization.
- `app.py` `__main__` block — `logging.getLogger("werkzeug").setLevel(logging.ERROR)`, `debug=False`, `use_reloader=False`, `threaded=True`. Pure launcher config; affects only stderr access-logging and dev-server reload behavior, never any response body, status, header, or stored state.

Per-edit pre-edit search log confirmed: the only PRD startup claim (§2.9 clock reads `2026-01-01T00:00:00Z` on startup) is satisfied by `db.py` on every fresh boot, independent of the install sentinel; error bodies are governed by the errorhandler chain, not `debug` mode. Neither fix is a PRD silence the impl pinned, nor a PRD/impl mismatch — they are invisible to every API client.

## Step 9: Complete PRD — 2026-06-21T02:49:51.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md` (full PRD-vs-implementation scan).

**Counts:** Source 275 lines / 44,310 chars → Result 275 lines / 45,724 chars; char delta +1,414 (no line-count change — all edits in-paragraph). Ambiguity-pins: 8 | Mismatch-revisions: 1.

**Changes** (`{section} — {kind} — {type} — {what} — {impl ref}`):
- §2.3 Pagination — insert — ambiguity — non-integer/out-of-bounds `limit`/`offset` rejected with `ERR_INVALID_REQUEST` (400) — helpers.py:23-35
- §2.3 Pagination — insert — ambiguity — `created_at` sort ties broken by insertion order — helpers.py:41
- §2.4 Versioning — revise — ambiguity — `version` initial value pinned to 1 — app.py:106/165/239 (svc touch services.py:30-34)
- §2.7 OCC — insert — ambiguity — `ERR_STALE_VERSION` evaluated after header/role/existence/body+FK gates, so 400/404 win over 412 — app.py:428-448 (booking), 935-940 (payment)
- §2.8 Request Ordering — insert — ambiguity — required strings must be non-empty; int fields reject bool/float — validators.py:21, 35-37
- §2.8 Request Ordering — insert — mismatch — on transition endpoints the state gate (`ERR_INVALID_STATE`) precedes validation of transition-specific body fields (`guarantee_count`/`actual_attendance`/`rooms_picked_up`), reversing the general body-before-state precedence — app.py:336-341 (lock-guarantee), 365-367 (actualize), 850-852 (record-pickup)
- §3.3 Booking release — insert — ambiguity — direct release permitted in any owning-event status as long as booking is `HOLD`/`DEFINITE`; an already-`RELEASED` booking yields `ERR_INVALID_STATE` — app.py:569-580
- §3.6 Room-block link — insert — ambiguity — new `RESERVED` link carries `rooms_picked_up` null until pickup recorded — app.py:762
- §3.8 Deposit gate — insert — ambiguity — an event with no schedule items (no deposit milestone) fails lock-guarantee with `ERR_DEPOSIT_UNSETTLED` — app.py:343-345, services.py:187-192

Behaviors PRD already pinned uniquely (charge rollup order/rounding, billable_count staging, started-hour rental, buffered double-booking, per-night block capacity, allocation waterfall, void deposit-lock simulation, percentage range→422, role matrix, response envelopes, logical clock default) were left unchanged.

---

## PIPELINE COMPLETE — 2026-06-21T02:49:51.000Z

All 9 steps complete. Final test state: **8/8 parallel rounds at 74/74 passed, 0 failed** (results.{1..8}.json persisted). Task directory contains SCAFFOLD.yaml + 2 design YAMLs, full test_helpers/ + test_suite/, working Flask implementation/, and the PRD chain PRD.md → PRD_FINALIZED.md (verbatim) → PRD_COMPLETED.md (8 ambiguity-pins + 1 mismatch-revision).
