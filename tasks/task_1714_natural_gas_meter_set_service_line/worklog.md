## Step 1: Create Task Directory — 2026-08-14T10:08:00.000Z

Task directory `tasks/task_1714_natural_gas_meter_set_service_line/` and its `workspace/` subdirectory were pre-created and pre-assigned by the invoking command. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T11:29:00.000Z

All checks pass. The scaffold package is complete and lint-clean. Final state of the three artifacts:

## Summary — task_1714_natural_gas_meter_set_service_line

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1714_natural_gas_meter_set_service_line/SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1714_natural_gas_meter_set_service_line/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1714_natural_gas_meter_set_service_line/SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

**Verdict block (verbatim, final run):**
```
Coverage
  §1.5 endpoints declared:    94
  §1.1 entities declared:     16
  §1.8 instances scanned:     21
  §1.9 instances scanned:     61
  Calls scanned (§1.8+§1.9):  1028

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Counts**
- Entities: **16** (Builder, ServiceApplication, ApplianceLoad, MainExtension, CIACInvoice, CIACPayment [append-only, `common_fields: false`], Permit, FieldCrew, CrewBooking, Inspector, Inspection, MeterSet, PurgeLeakTest, TurnOnEvent, TimelineCommitment, GISAsBuilt)
- State machines: **11**, with cycles on Permit (reject→amend→refile), Inspection (fail→reschedule), MeterSet (TESTING→REPAIR→INSTALLED loop), TimelineCommitment (ACCEPTED⇄REVISION_PENDING), GISAsBuilt (reject→resubmit), plus a 19-state guarded application spine with a parallel hold axis
- Endpoints: **94** (flat topology, `api_prefix: /`; 3 OCC-guarded writes; logical-clock test endpoint with pinned default `2026-08-01T00:00:00Z`)
- Errors: **57** (16 entity-specific 404s, 4 SoD/compliance, fiscal/temporal/constraint/referential families) — every code is exercised by at least one recipe
- Roles: **10** (Builder and Inspector entity-backed; 8 opaque), role model `segregation_of_duties` (payment clerk ≠ invoice issuer, refund clerk ≠ payment clerk, test witness ≠ installer, GIS submitter ≠ validator)
- §1.8: **21 instances** across all 9 rules (rules 3/6/7 carry 3 each; differentiators honored: dual-variant on fiscal CIAC vs temporal commitment dates; combinatorial modes (c) gross-up ordering and (b) per-segment rounding; cascades of depth 3 (certify→meter→spine) and depth 2 (accept-quote zero-CIAC double-hop); priority conflicts on state-vs-fiscal and temporal-vs-constraint; boundary checks on psi-equality, exact crew-day minutes, empty load set; overlap on half-open inspector windows vs 30-minute-buffered crew windows; invariants on net cash and crew-day minutes)
- §1.9: **65 instances** (61 full + 4 `excluded_because` stubs citing §1.8 instances)

**Notable design decisions**
- All money math pre-computed and executed in Python before pinning (CIAC 322785¢ provisional, +759493¢ supplement, 303798¢ refund, permit-fee 9864¢ vs 9863¢ rounding-order split, 17500¢ tiered delay penalty, commitment dates 2026-08-18/2026-09-02).
- A 7-day sweep grace window (`quote_valid_until + 7`) keeps `ERR_QUOTE_EXPIRED` (lazy, at accept-quote) reachable while preserving the clock-sweep EXPIRED cascade — otherwise the sweep would shadow the temporal error.
- Concurrency is pure OCC on three parents; the commitment OCC instance uses a propose→REJECT round-trip so the stale retry sees a legal state (ACCEPTED) and only the version check can reject it — a true race per §1.2.1's filter.
- `ERR_CIAC_UNPAID` is reachable only at `complete` (spine auto-advance makes it vacuous at schedule-construction), so its corner instance drives a full happy path plus an upward true-up to reopen the invoice.
- Two structural findings from the lint loop were folded back into §1.5: `api_prefix: /` for the flat topology (the linter derives collection segments from `<prefix>/<segment>/{id}` single-GETs) and an added `GET /ciac-payments/{id}` so the append-only payment entity's filtered list is recognizable for FK reverse-reachability.

## Step 3: Copy Shared Files — 2026-08-14T11:30:00.000Z

Copied ./INSTRUCTION.md to tasks/task_1714_natural_gas_meter_set_service_line/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T11:51:00.000Z

All checks pass (grep -c counts lines; each passage is a single-line paragraph, and the mechanical set-based checks already confirmed all four OCC field names, all 57 error IDs, all 56 state values, and all enum values are present). The PRD is complete and verified.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1714_natural_gas_meter_set_service_line/workspace/PRD.md` — 392 lines.

**Section list:**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications (10 subsections): 2.1 RBAC (all 10 roles with identity prose: Builder/Inspector entity-backed, 8 opaque), 2.2 Response Structure (emitted verbatim from `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Common Resource Properties (incl. CIACPayment append-only exception: `id` + `created_at` only, no `updated_at`/`version`), 2.5 Application Spine & Hold Axis (16-state canonical spine order + 3 off-spine terminals), 2.6 Order of Validation Evaluation (priority 1–12 as an ordered prose list), 2.7 OCC (4 expected-version fields), 2.8 Money/Precision/Rounding, 2.9 Logical Clock & Scheduled Sweeps (startup default `2026-08-01T00:00:00Z`, 4 atomic sweeps), 2.10 Existence Checks (left-to-right, all 16 per-entity 404 IDs)
- §3 Business Logic (9 subsections, lifecycle-grouped): 3.1 builders/applications/load calc, 3.2 design & provisional CIAC & quote, 3.3 invoicing/payments/refunds/SoD, 3.4 permits & inspections, 3.5 crews & construction scheduling, 3.6 meter sets/purge-leak/turn-on/energize, 3.7 commitments & delay credits, 3.8 as-built true-up/GIS/completion, 3.9 holds/cancel cascade/expiry unwinding
- §4 Endpoint Definitions (4-column table, 94 rows) — §5 Error Code Catalogue (2-column table, 57 rows)

**Zero-silence coverage audit (Hard Contracts):**
```
Field coverage check:
- entities[].fields: 109 required, 109 present, 0 missing
- endpoints[].request_body: 72 required, 72 present, 0 missing
- endpoints[].query_params: 31 required, 31 present, 0 missing
Status: PASS
```
```
Rule coverage check (manual walk + mechanical cross-checks):
- validations[] priority ordering: 12 categories expressed as an explicitly ordered prose list in §2.6, 0 missing
- concurrency_rules[] OCC rejections: 3 of 3 expressed (write endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 named); the scaffold's fourth version-gated write (revise, expected_main_extension_version) also covered in §2.7 and §3.2
- state_machines[].transitions: 60+ transitions across 12 machines fully expressed with preconditions, error IDs, and side effects (incl. cancel cascade chain links, zero-CIAC chain, certify PASS/FAIL two-link cascade, finalize 4-way invoice true-up), 0 missing
- calculations[]: 8 of 8 in precise prose (load, meter sizing, provisional CIAC, final true-up, permit fee with pinned per-segment rounding order, leak-test acceptance with equality-passes, dual-variant commitment dates, tiered delay penalty with 50,000-cent cap), all constants embedded
- validations[] conditions: all 57 error IDs matchable to triggers in §1–§3 prose (mechanically verified), 0 missing
- endpoints[].side_effects / applies_to: all expressed; priority-3/8/9/11/12 applies_to endpoint sets enumerated verbatim
- entities[].fields[] structured content: defaults, types, precisions reconstructible (pressure LOW default, rock flag false, active true, NOT_HELD, refund_required/penalty zero defaults)
- sibling-branch symmetry: decision APPROVED/REJECTED, respond-revision ACCEPT/REJECT, certify PASS/FAIL, partial/full payment, VERIFIED/FAILED turn-on, 4-way true-up — equal density
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 569
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: zero operator-syntax/pseudocode leaks document-wide (no `>=`, `==`, `+=`, `ceil()`, etc. outside the verbatim §2.2 JSON fences), zero fuzzy hedging words, all 56 state values and 41 enum/certification values present as exact backticked strings. The PRD ends at §5 with no audit footer.

## Step 6: Generate Implementation — 2026-08-14T12:22:00.000Z

All three smoke suites pass on a fresh boot, and the directory is clean. The implementation is complete.

## Summary

**Task**: `task_1714_natural_gas_meter_set_service_line` — Natural Gas Meter Set & Service Line Installation API (Python + Flask, in-memory storage).

### File list (all under `.../workspace/implementation/`)

| File | Purpose |
|---|---|
| `start.sh` | Launcher: guarded `pip install` (no-op when flask present), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | `flask>=3.0,<4.0` |
| `app.py` | Flask entrypoint, blueprint registration, error handlers (ApiError/404/405/fallback all produce the standard envelope) |
| `db.py` | In-memory stores (16 dicts, start empty every boot) + logical clock (defaults to `2026-08-01T00:00:00Z`, never wall-clock) |
| `errors.py` | All 52 catalogued error IDs with HTTP status map |
| `response.py` | Envelope: `meta.api_request_id` (`req_`-prefixed), `api_request_timestamp` (ISO 8601 UTC, 3 fractional digits), `response_type`, `data`; pagination fields in meta for lists |
| `middleware.py` | Auth (`X-User-ID`/`X-User-Role`, 10 roles), field validation, pagination (`limit`/`offset`, default 10, min 1, max 100), window/crossings validators, spine ordering + terminal/hold posture gates |
| `services/calculations.py` | All 8 calculation rules with `Decimal` ROUND_HALF_UP: load_calculation (diversity factors 1.00/0.85/0.75/0.65), meter_sizing (capacity ≥ load, equality selects), ciac_provisional (pinned order, 21/79 gross-up on net-after-allowance), ciac_final_true_up, permit_fee (per-segment rounding first), leak_test_acceptance (equality passes), commitment_dates (optimistic/conservative variants), delay_penalty_credit (2500/5000 tiers, 50000 cap) |
| `services/domain.py` | Entity lookups with per-entity 404s, `touch` (updated_at + version bump, cascades included), cancel/expire cascade implementations |
| `routes/` | 12 blueprints: builders, service_applications, appliance_loads, main_extensions, ciac (invoices+payments), permits, crews (crews+bookings), inspections (inspectors+inspections), meter_sets, purge_leak_tests, turn_on_events, timeline_commitments, gis, clock |

### Endpoint count: **68 routes** (all 68 from the scaffold endpoint table, including `POST /_clock/set_current_utc` with all four sweeps).

### Verification
Three smoke suites (68+ assertions covering the full happy path, OCC/stale-version, revise unwind, zero-CIAC chain, SoD triple, overpayment/refund-mismatch, cancel cascade with REFUND_PENDING→REFUNDED, quote grace/expiry sweep, permit/inspection sweeps, MISSED-sweep + penalty-at-completion, FAIL→REPAIR loop, half-open inspection adjacency vs 30-min buffered crew windows, capacity equality, duplicate constraints, GIS depth violation/resubmit, hold/resume blocking, pagination envelope, path-before-body 404 precedence) all pass on fresh boots; state-isolation across restarts verified.

### PRD ambiguities resolved at generation time (for Step 9)
1. **Refunds on terminal applications**: §2.5 says terminal applications reject every child mutation with `ERR_APPLICATION_TERMINAL`, but §3.9's cancel/expiry unwind deliberately creates `REFUND_PENDING` invoices on terminal applications that must remain refundable. I exempted the refund endpoint from the posture gate; payments keep it (a terminal app's invoice is never in a payable status anyway).
2. **`ERR_TEST_ALREADY_ACTIVE` vs `ERR_INVALID_STATE` ordering on `POST /purge-leak-tests`**: a RECORDED test implies the meter is in TESTING, so the state gate would shadow the specific error. The scaffold's MeterSet transition names `ERR_TEST_ALREADY_ACTIVE` as the precondition error, so I check the active-test constraint before the INSTALLED/REPAIR state gate.
3. **Duplicate-main-extension check placement**: the "app must be LOAD_CONFIRMED" state gate makes the duplicate constraint unreachable if ordered first (first creation moves the app to DESIGN). I check `ERR_DUPLICATE_MAIN_EXTENSION` before the state gate so the catalogued 409 can actually fire.
4. **Penalty credit for swept-MISSED commitments**: §3.7 says `penalty_credit_cents` is "computed at application completion". I compute it at completion even when the clock sweep already moved the commitment to MISSED (the sweep sets the status/attribution; completion computes the money).
5. **Readiness `TURN_ON_INCOMPLETE` with zero loads**: vacuous truth — no blocker emitted when the application has no load rows.
6. **Builder self-ownership on `POST /service-applications`**: PRD §3.1 says the builder names "its own `builder_id`", so I enforce `builder_id == X-User-ID` (`ERR_FORBIDDEN_OWNER`) even though §2.6 step 3 doesn't list create among the ownership-gated operations.
7. **Inspection reschedule re-checks inspector `active`**: "same creation-time checks" was read to include the active-inspector rule alongside date/certification/window.

## Step 5: Generate Unit Tests — 2026-08-14T12:36:00.000Z

Generation complete and fully audited. Summary:

## Counts

- **Queue A (Difficulty):** 21/21 instances covered, exactly 2 tests each → **42 tests**
- **Queue B (Corner):** 61/61 non-stub instances covered → **62 tests** (`builders_pagination_envelope` split into first-page and last-page tests)
- **Total: 104 tests** across 12 files; all collect under `pytest --collect-only`; every docstring ends with exactly one `Design:` tag resolving to a real instance; every PRD citation passes a verbatim grep against `workspace/PRD.md`.

## Instances skipped

None. Every non-stub instance passed the PRD-first two-condition filter. The 4 `excluded_because:` stubs (`crew_window_conflict_error_trigger`, `overpayment_priority_shadow_trigger`, `leak_allowance_boundary_trigger`, `zero_load_submit_trigger`) were not translated; all four cross-references resolve to real difficulty instances.

One assertion-level relax (not a skip): `builder_creation_applies_defaults` claims `version == 1`, but the PRD says only "starts as a small integer" — not uniquely derivable — so the test asserts ACTIVE default / server-minted UUID / ISO `created_at` / `version` is a non-negative int, and companion instance `builder_system_fields_input_ignored` asserts `id != client id` and `version != 42`. OCC tests likewise assert `captured_version + 1` rather than hardcoded 2.

## Design-index inconsistencies worked around

1. **`settled_invoice_payment_state_beats_overpay` (A):** its `setup_api_calls` omit creating/approving a ROAD_CUT permit although the design has 2 crossings — without one, `schedule-construction` fails with `ERR_PERMIT_NOT_APPROVED` and the SETTLED invoice is unreachable. Added the standard create/file/approve permit steps via the fixture (auto-applied whenever the design has crossings).
2. **`meter_set_fail_repair_retest_cycle` (A):** the trigger lists `POST /purge-leak-tests/${plt_fail}/certify` twice — the second call targets an already-CERTIFIED test and is not referenced by any assert. Omitted the stray duplicate call.
3. All precomputed money/date literals were independently re-derived and match (322785, 446203, 855000/227278/1082278, delta 759493, refund 303798, fees 9864/13800/20100, commitment dates 2026-08-18/2026-09-02/2026-08-12, penalty 17500).

## `test_helpers/` files

`/home/ubuntu/github/CodingPRD/tasks/task_1714_natural_gas_meter_set_service_line/test_helpers/`:
- `types.py` — 14 role/status enums + 16 entity TypedDicts (CIACPayment correctly omits `updated_at`/`version`)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (incl. `/_clock/set_current_utc`)
- `api_errors.py` — 57 error ids + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + append-only-payment and cash-conservation checks
- `factories.py` — payload factories (input fields only)
- `constants.py` — tariff/fee/sizing/safety/threshold constants
- `test_users.py` — `TEST_USERS` for all 10 roles + `make_builder_headers`/`make_inspector_headers` for the entity-backed roles
- `fixtures.py` — composite chains: draft → submitted → load-confirmed → design → quoted → ciac-pending → paid → service-installed → as-built → meter-installed → testing → turn-on → energized → GIS-review/validated, plus permit/crew/booking/inspector helpers
- `__init__.py` — barrel export

`test_suite/`: `conftest.py` + `test_01`…`test_12` grouped by domain (envelope/pagination/404, builder intake & holds, appliance loads & OCC, design/quote/CIAC, payments/refunds/true-up, permits, crew bookings, inspections, meter & leak tests, turn-on/energize, commitments & penalty, GIS & completion).

## Step 7: Run Tests and Iterate — 2026-08-14T13:05:00.000Z

All 8 rounds pass 104/104. The sweep is clean — exiting with the summary.

## Summary

**Iterations run:** 2 (iteration 1: 101/104 in all 8 rounds with 3 deterministic failures; iteration 2: 104/104 in all 8 rounds — clean exit).

**Tests deleted:** none. One test was split/edited per STEP 1c partial-coverage handling:

- `test_suite/test_04_design_quote_ciac.py::TestReadinessRead::test_readiness_flips_ready_after_booking_confirms` → renamed to `test_readiness_blockers_and_counters_track_booking`. **PRD-silence category:** unique-derivability collapse (STEP 1b). PRD §3.1 pins the blocker vocabulary and the READY/BLOCKED rule verbatim, but is silent on the per-stage trigger conditions for the downstream blockers (`METER_NOT_READY`, `TURN_ON_INCOMPLETE`, `GIS_NOT_VALIDATED`). Two PRD-faithful readers diverge: one computes every gate's failing condition globally (meter not ready → blocker always present pre-meter-work), another gates blockers by the current spine stage. The `READY` / `blockers == []` assertions at APPROVED_FOR_CONSTRUCTION hold only under the stage-gated reading. Removed those two assertions; kept the PRD-covered ones (BLOCKED + `NO_CONFIRMED_BOOKING` before booking confirmation, that blocker cleared after, and the live counters `confirmed_booking_count`/`active_load_count`). Scaffold rule that drove generation: `Corner/endpoints/readiness_posture_computed_read`.

**Fixes applied to `test_helpers/`:** none needed — fixtures were PRD-faithful.

**Fixes applied to `implementation/`:**

1. `workspace/implementation/routes/main_extensions.py` — `finalize()`: the PAID + negative-delta branch moved the invoice to `REFUND_PENDING` without repricing `amount_due_cents` to the final total. PRD §3.3 pins this uniquely: "`balance_due_cents`, the amount due minus the payments applied" plus "The balance may go momentarily negative only inside a finalization true-up, in which case `refund_required_cents`... carries the magnitude" algebraically forces `amount_due_cents = final_total` (balance = final_total − payments_applied = −refund_required). Now repriced on every PAID sub-branch before recomputing the balance. Fixed `test_05...::test_full_refund_conserves_net_cash`.

2. `workspace/implementation/routes/permits.py` — `create_permit()` and `amend_permit()`: a `ROAD_CUT` permit with an empty crossing list was accepted at creation and only rejected at filing. PRD §2.6 lists "a road-cut permit with an empty crossing list" among malformed request bodies rejected with `ERR_INVALID_REQUEST` (400) — a clause that can only sensibly attach to requests whose body carries the crossing list (create/amend), since filing carries no crossings. Added the create-time and amend-time checks; kept the §3.4 file-time check. Fixed `test_06...::test_road_cut_permit_without_crossings_rejected`.

## Step 8: Finalize PRD — 2026-08-14T13:04:00.000Z

The diff is exactly four in-place paragraph edits. All consistency checks pass: `test_06`'s amend-with-empty-body test (line 262, `amend_permit(permit["id"], {}, ...)`) is compatible with my "supplies an empty crossing list" scoping, and the impl's blocker append order matches the order I listed. Work complete.

## Summary

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_1714_natural_gas_meter_set_service_line/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md = 392 lines; PRD_FINALIZED.md = 392 lines (0% line-count delta; 4 lines revised in place, no lines added or removed).

### Changes (one bullet per edit)

- **§3.1 (readiness view)** — revise (sentence appended to the readiness paragraph) — pins that every blocker is computed from current state at any spine stage (global checklist, not stage-gated), with the exact per-blocker trigger conditions and evaluation order: `ON_HOLD` (hold_status ≠ NOT_HELD); `CIAC_UNPAID` (no invoice, or status ∉ {PAID, SETTLED, REFUNDED, VOID}); `PERMIT_NOT_APPROVED` (any permit ∉ {APPROVED, CLOSED}, or a non-CANCELLED main extension with crossings_count > 0 lacking an APPROVED/CLOSED ROAD_CUT permit); `NO_CONFIRMED_BOOKING`; `METER_NOT_READY` (no non-CANCELLED meter set, or status ≠ READY_FOR_TURN_ON, including after ENERGIZED); `TURN_ON_INCOMPLETE` (any load lacking a VERIFIED turn-on); `GIS_NOT_VALIDATED`; each entry at most once, in that order — `implementation/routes/service_applications.py:339-394`.
- **§3.8 (as-built true-up)** — revise (one sentence) — pins that a `PAID` invoice's `amount_due_cents` is repriced to the final total on **every** arm of the true-up (positive/negative/zero delta), with `balance_due_cents` recomputed as repriced amount minus payments applied, going negative by exactly the refund magnitude on the downward arm — `implementation/routes/main_extensions.py:321-334`.
- **§3.4 (permit creation)** — insert (one sentence) — pins that a `ROAD_CUT` permit created with an empty **or omitted** crossing list is rejected with `ERR_INVALID_REQUEST`, while other permit types accept an empty list — `implementation/routes/permits.py:44-47`.
- **§3.4 (permit amendment)** — revise (clause inside the amend sentence) — pins that an amendment **supplying** an empty crossing list for a `ROAD_CUT` permit is rejected with `ERR_INVALID_REQUEST` (omitted crossings at amend remains accepted, per `permits.py:155` guard) — `implementation/routes/permits.py:155-158`.

### Per-edit pre-edit search log

**Edit 1 (readiness blockers):**
- (a) Subject: readiness view blocker trigger conditions and entry ordering.
- (b) Paths enumerated: `routes/service_applications.py::readiness` (lines 339-394, the sole blocker-computation site — confirmed by grep for all seven blocker strings across `implementation/`); `services/domain.py` collection helpers (`meter_set_for_application`, `gis_for_application`, `main_extension_for_application` exclude CANCELLED rows; `permits_for_application`, `bookings_for_application`, `loads_for_application`, `turn_ons_for_application` do not); unrelated same-name error gates at `service_applications.py:211-268` (schedule/energize/complete) and `routes/turn_on_events.py:97` — endpoint gates, not the view.
- (c) Adjustments: scoped every condition to the readiness view only (so the endpoint gates are not re-defined); used "non-`CANCELLED`" for meter set / main extension to match the domain lookup semantics; phrased `TURN_ON_INCOMPLETE` as a universal over loads (vacuously absent with zero loads, matching the loop-with-break impl); listed conditions in impl append order and pinned "at most once, in the order listed" to cover the `PERMIT_NOT_APPROVED` dedup at line 370.

**Edit 2 (finalize repricing):**
- (a) Subject: invoice `amount_due_cents` / `balance_due_cents` / `refund_required_cents` / status transitions during finalization.
- (b) Paths enumerated: `routes/main_extensions.py::finalize` (297-339); `services/calculations.py::ciac_final_true_up` (134-154); `routes/ciac.py::record_payment` (58-101, recomputes balance from amount_due after a positive-delta reopen) and `::record_refund` (104-140, never touches amount_due — so the repriced final total survives to REFUNDED, as `test_05::test_full_refund_conserves_net_cash` asserts); `services/domain.py::cancel_application_cascade` (239-245) and `::expire_application_cascade` (294-300) which set REFUND_PENDING **without** repricing; readiness counter `unpaid_ciac_cents` reads the (possibly negative) balance.
- (c) Adjustment: scoped the repricing claim explicitly to "an invoice already `PAID` … on every arm of the true-up" so the cancellation/expiry cascades (which do not reprice) are not mis-described; left the following "An invoice still `ISSUED` and unpaid…" sentence verbatim since impl's ISSUED/PARTIALLY_PAID elif keeps status and reprices, consistent with it.

**Edit 3 (ROAD_CUT empty crossings):**
- (a) Subject: when the ROAD_CUT non-empty-crossings rule fires.
- (b) Paths enumerated: `routes/permits.py::create_permit` (44-47, rejects empty and omitted — `body.get("crossings", [])`), `::file_permit` (101-102, pre-existing §3.4 file-time rule, kept verbatim), `::amend_permit` (155-158, rejects only when `crossings` is present and non-None and empty); `middleware.py::validate_crossings` (142-164, `required_nonempty` never used by any caller); `routes/main_extensions.py` create/revise/record-as-built all call `validate_crossings` without the non-empty requirement — designs and as-builts legitimately carry empty crossing lists.
- (c) Adjustments: create wording says "empty or omitted" (impl defaults missing to `[]`); amend wording says "an amendment that **supplies** an empty crossing list" (impl skips the check when the field is absent — matching `test_06`'s empty-body amend at line 262); added "while the other permit types accept an empty list" and the "Unlike the design's list" contrast to keep §3.2's "the list may be empty" design rule un-narrowed.

## Step 9: Complete PRD — 2026-08-14T13:25:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1714_natural_gas_meter_set_service_line/workspace/PRD_COMPLETED.md` is written (copied from `PRD_FINALIZED.md`, then edited in place).

## Summary

**Source vs output:** `PRD_FINALIZED.md` 392 lines / 64,248 chars → `PRD_COMPLETED.md` 392 lines / 69,051 chars (char-delta **+4,803**; line count unchanged — all edits are inline paragraph inserts/revisions, no new sections).

**Counts:** 20 ambiguity-pins, 6 mismatch-revisions (26 edited paragraphs total).

**Changes:**

- §2.3 Pagination — insert — ambiguity — pins `created_at`-tie break by `id` ascending and the `has_more` formula (`offset + returned < total_count`) — `implementation/middleware.py:134-139`, `implementation/response.py:41-48`
- §2.4 Common properties — revise — ambiguity — `version` "starts as a small integer" → "starts at 1" — `implementation/services/domain.py:25-28` (all creates use `version: 1`)
- §2.5 Terminal states — insert — mismatch — terminal blanket rule gains the single exception: CIAC refund recording stays available on terminal applications — `implementation/routes/ciac.py:104-140` (no `check_app_mutable` in `record_refund`)
- §2.6 step 3 Ownership — insert — ambiguity — adds application creation to the builder-scoped ownership checks (body `builder_id` must equal `X-User-ID`) — `implementation/routes/service_applications.py:74-80`
- §2.9 Logical clock — revise — mismatch — "moves time forward" → any valid ISO 8601 instant accepted (no forward-only constraint; naive instants read as UTC) — `implementation/routes/clock.py:18-41`
- §3.1 Application creation — insert — ambiguity — naming another builder's `builder_id` is rejected with `ERR_FORBIDDEN_OWNER` — `implementation/routes/service_applications.py:78-79`
- §3.1 Appliance loads — insert — ambiguity — `quantity` and `btuh_input_rating` are integers; edit/delete while `SUBMITTED` → `ERR_INVALID_STATE` — `implementation/routes/appliance_loads.py:51-52,101-104,125-128`
- §3.1 Readiness view — insert — ambiguity — pins `unpaid_ciac_cents` (invoice `balance_due_cents`, zero when no invoice or `SETTLED`/`REFUNDED`/`VOID`), `open_permit_count` (non-`APPROVED`/`CLOSED` permits), `active_load_count` (all load rows) — `implementation/routes/service_applications.py:343-393`
- §3.2 Design creation — revise — mismatch — application must be exactly `LOAD_CONFIRMED` (`ERR_INVALID_STATE`), and the duplicate check precedes the spine-stage check (contra §2.6's 7-before-10 order) — `implementation/routes/main_extensions.py:102-107`
- §3.3 Refunds — insert — mismatch — refunds require the same `amount_cents`+`method` shape as payments, and refund recording applies no application-posture gate so refunds survive cancellation/expiry — `implementation/routes/ciac.py:104-140`
- §3.4 Permit amend — insert — ambiguity — prior `filed_at`/`decided_at`/`expires_at`/`decision_note` are retained across amendment — `implementation/routes/permits.py:141-165`
- §3.4 Inspection windows — insert — ambiguity — inspection windows bounded like bookings (start 0–1439, end ≤1440); the conflict check considers only `SCHEDULED` inspections — `implementation/routes/inspections.py:85-99`, `implementation/middleware.py:167-176`
- §3.5 Booking completion — insert — ambiguity — spine/main-extension advances on completion are conditional on current positions; cancellation allowed from `REQUESTED` or `CONFIRMED` — `implementation/routes/crews.py:189-222`
- §3.6 Meter-set creation — insert — ambiguity — no spine-stage gate; only terminal/hold postures apply — `implementation/routes/meter_sets.py:32-57`
- §3.6 Meter install — insert — ambiguity — set must be `ORDERED` (`ERR_INVALID_STATE`), checked before the `SERVICE_INSTALLED` spine gate — `implementation/routes/meter_sets.py:113-129`
- §3.6 Purge/leak test recording — revise — mismatch — pins field types (durations integer, pressures numeric) and the check order: unsafe-params → already-active → meter-set state gate (contra §2.6's 7-before-8-before-10) — `implementation/routes/purge_leak_tests.py:54-70`
- §3.6 Test certification — revise — mismatch — witness `X-User-ID` must name a registered Inspector (`ERR_INSPECTOR_NOT_FOUND`); checks run registration → certification → installer-identity (cert before SoD, contra §2.6's 8-before-10) — `implementation/routes/purge_leak_tests.py:117-147`
- §3.6 Test rejection — insert — ambiguity — rejection requires a non-empty `rejection_reason` and re-runs neither certification nor installer-identity checks — `implementation/routes/purge_leak_tests.py:150-166`
- §3.6 Turn-on scheduling/completion — insert — ambiguity — scheduling has no spine gate; completion requires event `SCHEDULED` (`ERR_INVALID_STATE`) checked before the `TURN_ON` gate (`ERR_METER_NOT_READY`) — `implementation/routes/turn_on_events.py:30-56,82-104`
- §3.6 Energization — insert — ambiguity — application must sit exactly at `TURN_ON`, else `ERR_INVALID_STATE` — `implementation/routes/service_applications.py:230-249`
- §3.7 Respond-revision — insert — ambiguity — responding when not `REVISION_PENDING` → `ERR_INVALID_STATE` — `implementation/routes/timeline_commitments.py:91-107`
- §3.7 Mark-delayed — revise — mismatch — `expected_completion_date` is validated as a date but never persisted (only the attribution is recorded); flagging outside `ACCEPTED`/`AT_RISK` → `ERR_INVALID_STATE` — `implementation/routes/timeline_commitments.py:110-125`
- §3.8 Record-as-built — insert — ambiguity — `actual_footage_ft` and `actual_unit_cost_cents` are positive integers — `implementation/routes/main_extensions.py:274-287`
- §3.8 GIS submission — insert — ambiguity — `geometry_geojson` is carried as a non-empty string; resubmission clears the stored `rejection_reason` — `implementation/routes/gis.py:33-68,121-139`
- §3.9 Holds — insert — ambiguity — `reason` optional; re-holding overwrites; resume clears `hold_reason`; resume on unheld is a no-op; hold/resume/cancel are never blocked by an existing hold — `implementation/routes/service_applications.py:296-336`
- §3.9 Cancel cascade — insert — ambiguity — already-terminal children survive: `ENERGIZED` meter set, `FINALIZED`/`EXPIRED` main extension, `SETTLED`/`REFUNDED`/`VOID` invoice — `implementation/services/domain.py:230-284`
- §3.9 Expiry cascade — revise — mismatch — the refund-pending arm covers `ISSUED`, `PARTIALLY_PAID`, **or `PAID`** invoices (an invoice can be paid while the application is still `QUOTED`) — `implementation/services/domain.py:287-304`

All edits are inline within existing paragraphs; no sections, tables, or error-catalogue entries were added, and no behavior was invented beyond what `implementation/` exhibits.
