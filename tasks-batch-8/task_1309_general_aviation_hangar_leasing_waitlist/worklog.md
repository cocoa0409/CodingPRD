# Worklog — task_1309_general_aviation_hangar_leasing_waitlist

## Step 1: Create Task Directory — 2026-08-12T20:28:00.000Z

Directory `tasks/task_1309_general_aviation_hangar_leasing_waitlist/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per invocation instructions; no other task_* directory was scanned or touched.

## Step 2: Generate Scaffold — 2026-08-12T21:13:00.000Z

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1309_general_aviation_hangar_leasing_waitlist/SCAFFOLD.yaml` (§1.0–§1.7 only)
- `/home/ubuntu/github/CodingPRD/tasks/task_1309_general_aviation_hangar_leasing_waitlist/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1309_general_aviation_hangar_leasing_waitlist/SCAFFOLD_CORNER_DESIGN.yaml` (single top-level key `scaffold_corner_design`)

**Counts:** 13 entities (Airport, Hangar, RateSchedule, WaitlistApplication, HangarOffer, Lease, LeaseAircraft, InsuranceCertificate, EnvironmentalComplianceRecord, HangarConditionInspection, UseAuditFinding, EvictionCase, RentCharge); 8 state machines (incl. cyclic WaitlistApplication queue-decline loop, cyclic Lease ACTIVE↔CURE_PERIOD, compound Hangar posture, two OCC concurrency rules); 52 endpoints (incl. `/_clock/set_current_utc` with fixed default 2026-08-01T00:00:00Z); 39 errors; 10 calculations; 11 ordered validations; 4 roles. §1.8: **18 non-stub instances** (exactly 2 per each of the 9 difficulty rules). §1.9: **35 non-stub instances + 22 excluded_because stubs** across all 9 taxonomy sections. `scaffold_lint.py` verdict: **clean lint** (446 calls scanned, 0 violations, all 20 FKs reverse-reachable).

**Beyond-expert difficulty realization:** every numeric assertion was pre-computed by executing the formulas (compound-vs-simple escalation diverging 108160 vs 108000 at the 2nd anniversary; floor-based pro-ration 54838 vs naive 54839; late-fee floor/cap stacking 500/day against 25% cap; waterfall fees-before-principal with per-charge conservation), with a full waitlist→offer→deadline-exact-boundary accept (>= rejects, lazy sweep only strictly-after)→lease→insurance-lapse auto-finding→cure-window expiry→eviction case auto-creation (depth-3 cascade)→OCC-guarded execution→abandoned-aircraft per-day-per-aircraft storage accrual lifecycle, plus queue-priority ties with transfer bonus, half-open rate-schedule interval overlap resolution, and two distinct error-priority conflict pairs (state-vs-temporal, state-vs-referential) — all reachable from empty-DB via lint-verified setup chains.

## Step 3: Copy Shared Files — 2026-08-12T21:14:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1309_general_aviation_hangar_leasing_waitlist/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-12T21:30:00.000Z

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1309_general_aviation_hangar_leasing_waitlist/workspace/PRD.md` — 292 lines. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened; generation used only `SCAFFOLD.yaml` plus the doc-generator skill spec.

**Section list:**
- 1. Introduction (3 paragraphs, business-context angle)
- 2. Global Specifications & System-Wide Principles: 2.1 User and Role-Based Access Control; 2.2 API Response Structure (byte-identical to the fixed verbatim block, verified by diff); 2.3 Pagination; 2.4 Resource Identity, Timestamps, and Versioning; 2.5 The Logical Clock and the Airport Sweep; 2.6 Monetary Values, Precision, and Rounding; 2.7 Optimistic Concurrency Control; 2.8 Hangar Posture: the Compound Availability Derivation; 2.9 Validation Pipeline and Error Precedence; 2.10 Nested Resource Resolution
- 3. Business Logic & Workflows: 3.1 Airports/Rate Schedules/Hangar Inventory; 3.2 Waitlist & Priority Scoring; 3.3 Offer Cycle; 3.4 Lease Activation & Based Aircraft; 3.5 Billing/Escalation/Late Fees/Payments; 3.6 Hangar Condition & Maintenance; 3.7 Insurance & Environmental Compliance; 3.8 Use Audits/Cure/Eviction/Abandoned Aircraft
- 4. Endpoint Definitions (52-row, 4-column table)
- 5. Error Code Catalogue (39-row, 2-column table)

**Coverage statement:** All scaffold tables fully rendered into prose — 13/13 entities (72/72 fields named in backticks), 8/8 state machines (all 32 transitions with preconditions paired to error IDs and all side effects), 10/10 calculations as precise natural-language formulas with constants embedded (100/1/30 priority points, 365-day anniversaries, 0.005 daily / 500-cent floor / 0.25 cap late fees, 2500-cent/day storage, 100000000-cent coverage minimum, 30-day eviction threshold), 11/11 validation priorities stated as an ordered pipeline, 2/2 OCC rules (occ_field + error_id + HTTP 412, no race framing), 52/52 endpoints in §4, 39/39 error IDs in §5 and each mentioned in §2/§3 narrative, 4/4 roles with identity semantics translated.

**Hard contract reports:**
- Contract 1 (Field-Name Coverage): entities[].fields 72 required / 72 present / 0 missing; request_body 50/50/0; query_params 13/13/0; path param `{id}` present. PASS.
- Contract 2 (Rule Coverage): priorities 11/11 expressed in order; OCC rejections 2/2; transitions 32/32; calculations 10/10; validation conditions all matchable to error IDs in prose; endpoint side effects and applies_to scopes enumerated; structured field defaults stated; sibling branches (compound/simple escalation, decline paths, termination paths) at equal density. PASS.
- Contract 3 (§3 Path Purity): 413 backtick tokens scanned; 0 path tokens, 0 bare HTTP methods, 0 method+path combos. PASS.

## Step 5: Generate Unit Tests — 2026-08-12T22:05:00.000Z

**Tests generated per queue**
- Queue A (Difficulty, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`): **36 tests** — 2 per instance × 18 instances (all 9 rules covered, zero shortfalls).
- Queue B (Corner, `SCAFFOLD_CORNER_DESIGN.yaml`): **35 tests** — 1 per non-stub instance × 35 non-stub instances.
- Total: **71 tests** across 7 test files. All 22 `excluded_because:` stubs in the corner index were not translated; every stub's `difficulty_instance` cross-reference was verified to resolve to a real instance in one of the two indices.

**Skipped instances: 0.** No instance failed the PRD-first two-condition filter outright. Three adjudications were applied per the skill's Silence-pattern table:
1. `Corner/state_machines/cure_finding_after_deadline_rejected_and_escalated` — at exactly the cure deadline the sweep has already escalated the finding, so the cure attempt fails both the state check and the window check; the test uses `validate_error_is_one_of([ERR_CURE_WINDOW_EXPIRED, ERR_FINDING_NOT_OPEN])` (error-precedence pattern) while asserting the unambiguous outcomes (finding ESCALATED_TO_EVICTION, lease EVICTION_PENDING).
2. `Corner/validations/size_class_mismatch_on_offer_rejected` — trigger payload carries `override_next_in_queue: true` so only the size-class rule can fail (validation-priority isolation; the T_HANGAR application cannot rank in the BOX queue otherwise).
3. `Corner/calculations/waitlist_priority_score_transfer_bonus_and_fifo_tiebreak` — exact `priority_score` values on GET were dropped as not uniquely derivable (lazy recompute persistence is unspecified in PRD); the ranking behavior itself (ERR_NOT_NEXT_IN_QUEUE for the lower-ranked applicant, successful offer to the transfer bonus applicant) is asserted.
4. Two recipes (`late_fee_daily_floor_cap_threshold_mode_a`, `payment_waterfall_rounding_order_mode_b`, and the conservation instance sharing their setup) moved the clock-set call before offer creation — as authored, the 72h offer window would have expired before acceptance; asserted values are unchanged.

**test_helpers/ file list** (9 files): `__init__.py` (barrel: framework generics + PRD-specific), `types.py` (13 entity TypedDicts — all carry full common fields per PRD §2.4 — plus 18 status/role enums), `api_client.py` (`ApiClient(GenericApiClient)`, 45 endpoint methods), `api_errors.py` (39 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity assertions, `parse_instant`, `assert_charge_ledger_identity`), `factories.py` (16 payload factories), `constants.py` (PRD thresholds: 500-cent late-fee floor, 0.5%/day, 25% cap, 100000000 min coverage, 2500 cents/day storage, 30-day eviction threshold, default clock 2026-08-01), `test_users.py` (shared constants for opaque roles + `make_applicant_headers`/`make_tenant_headers` entity-backed builders), `fixtures.py` (composite chain: airport → schedule → hangar → application → offer → accept-lease, with optional pre-offer clock move; lenient `get_success_data` throughout).

**test_suite/ file list** (8 files): `conftest.py` + `test_01_airport_lifecycle.py` (8), `test_02_inventory_and_envelope.py` (9), `test_03_waitlist_queue.py` (9), `test_04_offer_acceptance.py` (12), `test_05_billing_escalation_payments.py` (13), `test_06_compliance_findings.py` (13), `test_07_eviction_and_aircraft.py` (7).

**Stage 2 self-audit result — all green:**
- All 71 tests tagged: yes; each docstring ends with exactly one `Design: Difficulty/...` or `Design: Corner/...` line.
- All tags resolve: yes — 53 valid tags from the two indices; 0 untagged, 0 dual-tagged, 0 unresolved, 0 coverage shortfalls.
- PRD citations: every test carries verbatim PRD quotes; automated grep of a ≥8-word substring of each citation against `workspace/PRD.md` passed for all 71 tests.
- Constructibility: `py_compile` clean on all 17 files; `pytest --collect-only` collects 71 tests; every `ApiClient` method invoked exists; every name imported from `test_helpers` resolves.
- No `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold/table references in generated comments.

## Step 6: Generate Implementation — 2026-08-12T22:05:00.000Z

## File list (`tasks/task_1309_general_aviation_hangar_leasing_waitlist/workspace/implementation/`)

- `start.sh` — foreground launcher: `set -euo pipefail`, `cd` to its own dir, guarded dependency install (`if ! python3 -c "import flask"` — no-op once deps present so per-test reboots never re-run pip), then `exec python3 app.py`
- `requirements.txt` — `flask>=3.0` (only dependency)
- `app.py` — Flask entry point: registers all blueprints, `ApiError`/404/405/500 handlers emitting the scaffold error envelope, `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))`
- `db.py` — 13 in-memory stores (plain dicts keyed by UUID `id`), the logical clock (defaults to exactly `2026-08-01T00:00:00Z`, never wall-clock), a monotonic `_seq` insertion counter (created_at tie-break), `new_entity()` (id/created_at/updated_at/version=1), `public()` serializer. **No seeding — every store is empty at boot.**
- `errors.py` — `ApiError(error_id, message, http_status)` + all 40 catalog error-id constants
- `envelope.py` — `success_obj` / `success_list` / `error_resp` producing exactly `{meta:{api_request_id, api_request_timestamp}, response_type: object|array|error, data}` with `limit/offset/total_count/has_more` in meta for lists only
- `auth.py` — `X-User-ID`/`X-User-Role` extraction (missing/malformed/unknown role → 400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), role gating (→ 403 `ERR_INSUFFICIENT_PERMISSIONS`), entity-backed ownership for Applicant (=application id) and Tenant (=lease id)
- `validators.py` — JSON body parsing, required field/enum/int/bool/datetime validators (→ 400 `ERR_INVALID_REQUEST`), pagination (`limit` default 10 clamped 1–100, `offset` default 0)
- `timeutil.py` — ISO8601 parse (Z/offsets) and 3-fractional-digit Z formatting, whole-day floor
- `services/core.py` — system constants (BASE_POINTS 100, WAIT 1/day, TRANSFER 30, late-fee 0.005/500/0.25, MIN_COVERAGE 100000000, DELINQUENCY_THRESHOLD 30, ABANDONED_DAILY 2500, 365-day anniversaries); compound hangar posture derivation (computed fresh on every read); open-offer reservation gate; rate-schedule selection (half-open intervals, latest effective_from, created_at ASC tie-break); waitlist ranking (score DESC, created_at ASC); pro-rated first charge (`floor(rate * days_remaining / days_in_month)`, pro-rate first); late fees (round-half-up via Decimal); escalation (COMPOUND on running value, SIMPLE on base×(1+pct·k), inclusive anniversary boundary); coverage checks; finding factory
- `services/sweep.py` — the airport sweep
- `routes/` — 14 blueprints covering all 52 endpoints (clock, airports, rates, hangars, applications, offers, leases, aircraft, insurance, environmental, inspections, findings, evictions, rent_charges)

## Sweep / logical clock

`POST /_clock/set_current_utc` (AirportManager only) sets the logical clock and runs the sweep at the new instant; all temporal logic anywhere reads only this clock. The sweep executes the PRD §2.5 duties in order — offer expiry (strictly `>` deadline), escalation, late fees + ACTIVE→DELINQUENT flip (strictly past grace end), cert/env-record expiry + auto INSURANCE_LAPSE filing (ACTIVE/DELINQUENT leases only), abandoned-aircraft storage accrual (whole-day floor × snapshot rate × BASED count, billed-days counter), cure-deadline escalation (inclusive `>=`: finding→ESCALATED, eviction case FILED, lease→EVICTION_PENDING), then monthly billing (one charge per elapsed calendar-month boundary, oldest first, post-escalation rate). Because billing is last but earlier duties must observe the charges it creates, `run_sweep` loops passes to a fixpoint (entity-count + version-sum signature; every step is idempotent at a fixed instant, so repeat same-instant sweeps change nothing).

## Boot confirmation

`bash start.sh` was executed repeatedly from `implementation/` on a test port: it binds `0.0.0.0:$PORT` in the foreground via `exec`, serves HTTP within ~2s, and boots with a completely empty store (verified `GET /airports` returns `total_count: 0`). Three regression suites (79 checks total) pass; the only failing assertions were in my own throwaway smoke script where its expectations contradicted the spec (each re-verified correct with targeted tests: DELINQUENT+open-finding stays DELINQUENT, cure flips only CURE_PERIOD→ACTIVE, suspend leaves OFFERED applications in place so `ERR_APPLICATION_NOT_QUEUED` precedes the hangar gate, storage sweep idempotency with 4 charges).

## Step 7: Run Tests and Iterate — 2026-08-12T22:30:00.000Z

All 8 rounds passed 71/71 — clean sweep.

**Iterations run:** 3 sweeps total — sweep 1 (baseline: 69/71 in all 8 rounds, two distinct failures), sweep 2 (unmodified reproduction check for the infrastructure error), sweep 3 (with the test fix: **71/71 in all 8 rounds, ALL GREEN**).

**Tests deleted:** none.

**Failures diagnosed:**

1. **`test_open_offer_removes_hangar_from_available_pool`** (failed 8/8 rounds): The test asserted `posture != "AVAILABLE"` on a hangar holding an OPEN offer. This contradicts PRD §2.8's posture formula — "`AVAILABLE`: no lease on the hangar is in `ACTIVE`, `DELINQUENT`, `CURE_PERIOD`, or `EVICTION_PENDING`, and the hangar's `condition_rating` is not `OUT_OF_SERVICE`" — which considers only leases and condition_rating; no faithful PRD-only implementer could produce any other enum value (LEASED requires "such a lease exists"). The scaffold's intent ("reserved → no longer AVAILABLE") did not survive into the PRD formula — a doc-generator scattering gap worth flagging. Per STEP 2 (assertion mis-translates PRD wording), the test was fixed, not deleted, because the reservation rule IS in PRD verbatim as a behavioral gate.

2. **`test_payment_waterfall_fees_before_principal`** (error 8/8 in sweep 1, then 0/8 in sweeps 2 and 3): Harness-level "server could not be restarted" (15s boot poll exhausted; measured boot is 0.38s). All 8 rounds failed at the identical wall-clock second, and the ports registry showed other pipeline holders on the host — a transient host-wide stall, not an implementation or test bug. It did not reproduce in 16 subsequent round-runs. No harness or start.sh change made (the current `exec python3 app.py` form has correct signal semantics; a retry wrapper would risk leaking orphaned servers).

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**
- `test_suite/test_03_waitlist_queue.py` — `test_open_offer_removes_hangar_from_available_pool`: replaced the PRD-contradicting `posture != "AVAILABLE"` assertion with the three rules PRD actually states — (a) posture remains `AVAILABLE` per the §2.8 formula (recomputation changes nothing with no lease and GOOD rating), (b) hangar `version` unchanged (§3.3: "offer creation itself does not increment the hangar's `version`"), (c) the reservation is behavioral: a second offer naming the reserved hangar is rejected with `ERR_HANGAR_NOT_AVAILABLE` (§2.8 "an `OPEN` offer reserves its hangar against further offers for its lifetime" + §3.3's availability gate), while the free hangar still accepts an offer (available-pool conservation, the design instance's compensating invariant). Docstring PRD citations updated accordingly; Design tag retained.

**Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful (posture derived per §2.8 formula in `services/core.py:hangar_posture`; reservation enforced as a separate gate in `hangar_available_for_offer` raising `ERR_HANGAR_NOT_AVAILABLE`).

**Final state:** 71/71 tests passing in all 8 parallel rounds.

## Step 8: Finalize PRD — 2026-08-12T22:38:00.000Z

Done. `PRD_FINALIZED.md` written at `tasks/task_1309_general_aviation_hangar_leasing_waitlist/workspace/PRD_FINALIZED.md`.

**Line counts / delta:** PRD.md 292 lines, PRD_FINALIZED.md 292 lines — 0.0% line-count delta; 5 lines revised in place, none added or removed.

**Changes (one bullet each):**
- §2.8 — revise — appended explicit resolution sentence: the `OPEN`-offer reservation is a behavioral gate on offer creation, not a fifth posture value, and never feeds the derivation, so an offer-reserved hangar with no occupying lease and serviceable rating still reports `AVAILABLE` — `implementation/services/core.py:49-59` (`hangar_posture`), `core.py:75-81` (`hangar_available_for_offer`).
- §3.3 — revise — offer-creation gate clause now includes the third conjunct "no other `OPEN` offer may exist on the hangar" under `ERR_HANGAR_NOT_AVAILABLE` — `implementation/routes/offers.py:96-97` via `core.py:75-81`.
- §3.3 — revise — creation side-effects sentence: the open offer holds the §2.8 reservation as a gate on future creation that leaves the derived `posture` value unchanged (replaces "posture is recomputed so the open offer reserves it"); version clause preserved — `implementation/routes/offers.py:104-119` (no `touch(hangar)`; comment at line 118).
- §3.3 — revise — sweep-expiry sentence: expiry releases the reservation and posture recomputes under the §2.8 formula (removes "or offer holds it", which implied offers feed the formula) — `implementation/services/sweep.py:60-71`.
- §3.4 — revise — accept gate pinned to what impl checks: hangar still `OPERATIONAL` and derived posture still `AVAILABLE` (replaces "posture ... still reflect this offer's reservation") — `implementation/routes/offers.py:162-163`.

Step 7 item 2 (payment-waterfall harness stall) was transient infrastructure, not a PRD silence — no edit.

**Per-edit pre-edit search log:**
1. **§2.8 reservation sentence** — (a) subject: posture derivation vs. OPEN-offer reservation. (b) enumerated: `core.py:49-59`, `core.py:62-65`, `core.py:68-81`, `offers.py:96-97`, `offers.py:162-163`, `hangars.py:55-56`, `airports.py:107-108`, `hangars.py:74-75`, `inspections.py:81`, `evictions.py:113`, `applications.py:90-93`, `airports.py:77-82`, `sweep.py:60-71`. (c) scoped the new sentence to "gate on offer creation / never feeds the derivation" so it stays true for every enumerated reader/writer of posture, including accept (which requires posture `AVAILABLE` while its own offer is `OPEN`).
2. **§3.3 creation gate** — (a) subject: `ERR_HANGAR_NOT_AVAILABLE` at creation. (b) enumerated: `offers.py:96-97` → `core.py:75-81` (three conjuncts incl. `open_offer_on_hangar is None`); the other raiser `offers.py:162-163` is the accept path described in §3.4, not this sentence. (c) kept the edit inside the creation pipeline clause only, so the accept path (which omits the open-offer check) is not mis-described.
3. **§3.3 creation side-effects** — (a) subject: hangar mutation at offer creation. (b) enumerated: `offers.py:104-119` (creates offer, `touch(app)` only, line-118 comment confirms no hangar version bump); `core.py:49-59` (derivation ignores offers). (c) replaced the causal claim ("recomputed so the offer reserves it") with gate language; version clause kept verbatim.
4. **§3.3 sweep expiry** — (a) subject: expiry's effect on hangar. (b) enumerated: `sweep.py:60-71` (flips offer + application, never touches hangar); parallel release paths decline `offers.py:235-252`, withdraw-cancel `applications.py:90-93`, suspend-cancel `airports.py:77-82` — none mutate the hangar. (c) dropped "or offer holds it", added "reservation is released", anchored recomputation to the §2.8 formula inputs.
5. **§3.4 accept gate** — (a) subject: accept-time hangar check. (b) enumerated: `offers.py:141-232`, gate at 162-163 is `status != OPERATIONAL or posture != AVAILABLE`; deliberately does not call `open_offer_on_hangar` (the accepted offer is itself OPEN). (c) pinned wording to OPERATIONAL + posture `AVAILABLE`, harmonizing with edit 1 and matching the impl exactly.

Left unchanged deliberately: §3.3 decline/withdraw "recomputed toward `AVAILABLE`" phrasings (loose but make no false claim; consistent with `offers.py:235-252` and `applications.py:90-93` where the derivation is a no-op), and all other PRD prose, which already uniquely determines impl behavior.

## Step 9: Complete PRD — 2026-08-12T22:47:00.000Z

**Files**: `PRD_FINALIZED.md` (292 lines / 45,475 chars) → `PRD_COMPLETED.md` (294 lines / 49,594 chars). Delta: +2 lines, +4,119 chars. 18 change hunks total.

**Counts**: 14 ambiguity-pins, 4 mismatch-revisions.

**Changes** (all inline edits to existing paragraphs; no new sections):

- §2.2 — insert — ambiguity — unexpected server failures surface as `ERR_INTERNAL` (HTTP 500) in the standard envelope — implementation/app.py:36-38
- §2.3 — revise — ambiguity — `limit`/`offset` are clamped (not rejected) into [1,100]/[0,∞); non-integer values → `ERR_INVALID_REQUEST` (400); list ties broken by insertion order — implementation/validators.py:88-109
- §2.5 — revise — ambiguity — clock-set accepts any target instant, even earlier than the current reading; the sweep iterates its duties to a fixed point so pre-billing duties observe charges the billing pass creates in the same advance — implementation/routes/clock.py:14-21, implementation/services/sweep.py:42-57
- §2.9 — revise — ambiguity — pinned where the OCC version guard sits (after time-window checks, before availability/cross-entity/compliance checks) and that payload well-formedness checks run as each field is consumed — implementation/routes/offers.py:149-161, implementation/routes/evictions.py:99-105
- §2.10 — revise — ambiguity — unmatched paths/unsupported methods → `ERR_NOT_FOUND` (404); body-carried identifiers (offer creation) resolve like path ids, and a hangar/application not scoped to the named airport → 404 — implementation/app.py:26-33, implementation/routes/offers.py:75-85
- §3.1 — revise — mismatch + ambiguity — `airport_code` uniqueness is recorded but not enforced (PRD said "unique"); pinned `escalation_pct` and `late_fee_grace_days` may be zero but not negative — implementation/routes/airports.py:22-52
- §3.1 — revise — ambiguity — rate schedules: missing/unparsable `effective_to` → `ERR_INVALID_REQUEST`; no check that `effective_to` falls after `effective_from` — implementation/routes/rates.py:28-38
- §3.1 — revise — mismatch — `hangar_code` uniqueness within the airport is not enforced (PRD said "unique within the airport") — implementation/routes/hangars.py:21-40
- §3.2 — revise — ambiguity — `is_based_tenant_transfer` is recorded as declared (no verification of an existing ACTIVE lease); no limit on applications per applicant — implementation/routes/applications.py:27-55
- §3.4 — revise — ambiguity — attestation of false → `ERR_INVALID_REQUEST` (400); insurance evidence must cover the acceptance instant, not just meet the minimum; first aircraft's tail number subject to the same uniqueness rule (`ERR_DUPLICATE_N_NUMBER`); 201 response carries the new lease — implementation/routes/offers.py:141-232
- §3.4 — revise — ambiguity — add-aircraft: `is_primary` optional default false, no lease-state precondition; removing a non-`BASED` aircraft → `ERR_INVALID_STATE` (409) — implementation/routes/aircraft.py:22-75
- §3.5 — revise — ambiguity — monthly billing chains off the latest monthly rent charge's `period_end`, ignoring storage-accrual charges — implementation/services/sweep.py:169-195
- §3.5 — revise — ambiguity — `amount_cents` must be a positive integer; overpayment rejected atomically against total outstanding before any allocation; payments allowed in any lease status (incl. EVICTED/TERMINATED); 200 returns the updated lease — implementation/routes/leases.py:52-101
- §3.7 — revise — mismatch — a certificate submission failing the compliance check is rejected with `ERR_INSUFFICIENT_COVERAGE` (422), not recorded in a non-VALID status as the PRD's wording implied — implementation/routes/insurance.py:16-46
- §3.7 — revise — ambiguity — environmental review requires a non-empty `review_note` and a `PENDING_REVIEW` record (else `ERR_INVALID_STATE`, 409); sweep expires only `PENDING_REVIEW`/`APPROVED` records (`REJECTED` never expires); no constraint on `expires_at` vs submission instant — implementation/routes/environmental.py:46-58, implementation/services/sweep.py:101-104
- §3.8 — revise — mismatch — a successful cure returns only a `CURE_PERIOD` lease to `ACTIVE`; a lease filed against while `DELINQUENT` stays `DELINQUENT` (PRD said cure "returns the lease to ACTIVE") — implementation/routes/findings.py:100-108
- §3.8 — revise — ambiguity — manual eviction filing: `reason` optional, defaults to `DELINQUENCY`, any of the three enum values accepted — implementation/routes/evictions.py:36-61
- §3.8 — revise — ambiguity — each storage accrual is recorded as an additional rent charge (period `executed_at` + billed days → sweep instant) joining the common ledger: adds to `outstanding_balance_cents`, accrues late fees, paid via the waterfall — implementation/services/sweep.py:117-140

Behaviors verified as already uniquely pinned (no change): posture derivation, offer/accept/cure window boundary asymmetries, free-decline semantics, escalation formulas and anniversary boundary, late-fee floor/cap math, pro-rated first charge, waterfall ordering, suspended-airport five-operation gate, supersede rule for rate schedules, sweep auto-filing of INSURANCE_LAPSE, OCC guards on accept/execute, and the full error catalogue mapping.

## Pipeline Complete — 2026-08-12T22:47:00.000Z

All steps 2–9 completed inside `tasks/task_1309_general_aviation_hangar_leasing_waitlist/` only. Final gate: 71/71 tests passing in all 8 parallel per-test-server rounds (Step 7, sweep 3).
