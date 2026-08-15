# Worklog — task_1735_air_freight_forwarding_consolidation

## Step 1: Create Task Directory — 2026-08-14T12:07:00.000Z

Task directory `tasks/task_1735_air_freight_forwarding_consolidation/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per instructions (no index scan, no creation).

## Step 2: Generate Scaffold — 2026-08-14T13:12:12.716Z

Scaffold generated for task_1735 (Air Freight Forwarding & Consolidation), written purely from the scenario + skill spec — no sibling tasks were inspected.

**Files written**
- `/home/ubuntu/github/CodingPRD/tasks/task_1735_air_freight_forwarding_consolidation/SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1735_air_freight_forwarding_consolidation/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:`
- `/home/ubuntu/github/CodingPRD/tasks/task_1735_air_freight_forwarding_consolidation/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:`

**Counts**
- 9 entities: Shipper, FlightBooking, MasterWaybill, HouseWaybill, ScreeningRecord, CustomsEntry, RateAgreement, MilestoneEvent (append-only, `common_fields: false`), Claim
- 6 state machines (Shipper, FlightBooking, MasterWaybill, HouseWaybill, CustomsEntry, Claim) — three cyclic (HWB screening revision loop, customs rework loop, claim counteroffer/rebuttal loop) plus compound bubble-ups (booking auto-DEPARTED, HWB auto-CLEARED)
- 6 calculations: chargeable_weight (QUOTED/FINAL variants, 0.5 kg ceiling), freight_rate_selection (IATA lowest-applicable-rate, min-over-tiers), charge_line_total (pinned per-line-round-then-sum), spot_surcharge_determination (pinned candidate-excluded snapshot order), liability_limit (STANDARD 22 SDR×1.35 vs DECLARED_VALUE variants), demerit_suspension (≥3 inclusive)
- 40 endpoints (incl. `POST /_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` fixed default), 30 error codes, 11 ordered validation rows, 6 opaque roles (segregation-of-duties model), 1 OCC concurrency rule (`consolidate-stale-mawb-version`, 412)
- Difficulty design: 18 instances (2 per each of the 9 rules) — differentiation honored, e.g. dual variants on HWB rating vs Claim liability; combinatorial modes (a) tiered selection vs (b) rounding order; cascades from booking-cancel (depth 3) vs screening-reject (depth 3); validation pairs state×safety and safety×fiscal; boundaries on capacity kg (consolidate) vs claim-deadline time (claims); overlap semantics half-open (RateAgreement) vs 30-min buffered (MAWB tender windows); invariants on weight vs money
- Corner design: 44 active instances + 4 `excluded_because` stubs, covering all 9 claim-extraction-guide sections; every error in the catalog is triggered by at least one instance; every formula-derived assert uses precomputed literals (e.g. 184.26 vs 184.25 rounding proof, 2376.00 liability cap, 85.00% spot threshold)

**Notable design decisions**: flat topology with FK reverse-lookups; spot-surcharge flag locked at consolidation from a candidate-excluded utilization snapshot (kills the circular dependency); milestone rank rule persists out-of-order events with `out_of_order=true` instead of rejecting them; MAWB close gated on claim terminality (4th cross-entity pair); path params normalized to `{id}` for the lint's FK reachability derivation.

**Lint verdict (verbatim)**:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(800 calls scanned across 18 §1.8 + 44 §1.9 instances, 40 endpoints, 9 entities.) A separate self-audit additionally confirmed: no forbidden concurrency vocabulary, unique instance names across both files, all grounds resolve, all errors referenced.

## Step 3: Copy Shared Files — 2026-08-14T13:12:44.625Z

Copied `./INSTRUCTION.md` to `tasks/task_1735_air_freight_forwarding_consolidation/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T13:22:00.000Z

PRD generation complete for task_1735. Output: `/home/ubuntu/github/CodingPRD/tasks/task_1735_air_freight_forwarding_consolidation/workspace/PRD.md`

**Line count:** 315 lines

**Section structure:**
- §1 Introduction (3 paragraphs — business context, system scope, two governing commitments: capacity scarcity + compliance gates)
- §2 Global Specifications, 10 subsections: 2.1 RBAC (with per-role `identity: opaque` prose for all 6 roles and the conditional customs-transition role map), 2.2 Response Structure (verbatim fixed block, untouched placeholders), 2.3 Pagination, 2.4 Common Resource Properties (incl. explicit `MilestoneEvent` exception — only `id`/`created_at`, no `updated_at`/`version`), 2.5 OCC on MasterWaybill, 2.6 Validation Order (all 11 priorities enumerated as a numbered list), 2.7 Capacity Accounting (consumed set definition + `utilization_pct` formula in prose), 2.8 Money/Rating/Precision (pinned line-rounding order with the 184.26 vs 184.25 worked example), 2.9 Logical Clock (fixed startup default `2026-08-01T00:00:00Z`, eager + lazy cutoff), 2.10 Cross-Resource Cascades
- §3 Business Logic, 8 subsections grouped by lifecycle: 3.1 Shippers & Rate Agreements, 3.2 Flight Booking procurement/cancel, 3.3 House Waybill screening & demerit ledger, 3.4 Consolidation under MAWB (OCC + 8-rule chain + deconsolidation + void/close), 3.5 Rating (chargeable weight QUOTED/FINAL, lowest-applicable-rate tariff selection, spot surcharge 5-step pinned evaluation), 3.6 Tender & Milestones (window buffer, FINAL re-rate, rank rule), 3.7 Customs Entries & broker handoff, 3.8 Claims & liability variants
- §4 Endpoint table — 40 rows, 4 columns (Method / Path / Description / Authorized Roles); matches scaffold endpoint count exactly
- §5 Error catalogue — 30 rows, 2 columns (Error ID / HTTP Status)

**Audit results — all three hard contracts PASS:**
- Contract 1 (field coverage): 70/70 entity fields, 36/36 request-body names, 17/17 query params, 2/2 path params present in backticks. One gap found on first pass (`houseWaybillId` only existed in the §4 table) and repaired by naming it in the §3.4 deconsolidation narrative.
- Contract 2 (rule coverage): 39 targeted spot checks all pass — OCC triple (endpoint + `expected_master_waybill_version` + `ERR_STALE_VERSION`/412), validation priority ordering, inclusive thresholds (demerit ≥3, spot ≥85.00, filing deadline inclusive), dual-variant calculations (QUOTED/FINAL, STANDARD/DECLARED_VALUE), per-line-rounding pinned order, tender 30-minute buffer with both inequalities, 3-link booking-cancel cascade, `TENDERED` MAWB system-only void, claim caps (`approved ≤ min(claimed, limit)` vs `counter ≤ limit` asymmetry preserved), all 30 error IDs mentioned in §2/§3, all 29 state values and 47 enum values present.
- Contract 3 (§3 path purity): 403 backtick tokens scanned in §3, zero path/method violations.

**Notable scattering/serialization decisions:**
- The consolidation request's two parameters were split per the scattering rule: `hwb_id` and `expected_master_waybill_version` appear in §3.4's workflow, while the OCC rejection semantics live in §2.5 and the priority position in §2.6.
- Constants embedded with unit conversion: the IATA divisor appears both as "0.006 cubic metres per kilogram" and "one kilogram per 6000 cubic centimetres"; liability as "22 Special Drawing Rights per kilogram ... at 1.35 USD per SDR".
- Sibling-branch symmetry held for: the three `resolve-review` outcomes (each getting amount rules + error split), the three-link cascades (booking cancel and screening rejection both enumerated link-by-link), and all milestone rank transitions.
- The counteroffer loop (`COUNTERED → UNDER_REVIEW` rebut vs `COUNTERED → SETTLED` accept) is told as a claimant-choice narrative, with `review_round_count` increment on rebut only.
- `consumed_weight_kg` set membership (CONSOLIDATED/TENDERED/IN_TRANSIT, excluding DELIVERED/detached/VOID-parent waybills) is stated once precisely in §2.7 and referenced from §3 workflows, avoiding contradictory restatements.

## Step 5: Generate Unit Tests — 2026-08-14T13:58:00.000Z

All audits pass. Generation complete. Final summary:

## File inventory

**`test_helpers/`** (9 files) at `/home/ubuntu/github/CodingPRD/tasks/task_1735_air_freight_forwarding_consolidation/test_helpers/`:
- `types.py` — 8 status enums + role enum + 9 entity TypedDicts (MilestoneEvent correctly omits `updated_at`/`version` per the append-only rule)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (clock, shippers, rate agreements, bookings, master waybills incl. consolidate/deconsolidate/tender/void/close/milestones, house waybills incl. submit/recall/cancel/measure, screening resolve, customs entries/transition, claims lifecycle)
- `api_errors.py` — all 29 error IDs + HTTP map, registered via `set_error_http_status_map()`
- `assertions.py` — per-entity `assert_*` + `assert_money_equal` / `assert_weight_equal` (2dp half-up / 0.5 kg step aware)
- `factories.py` — payload factories, input fields only
- `constants.py` — DIM_FACTOR 0.006, spot threshold 85.00, SDR 22×1.35, demerit limit 3, default clock 2026-08-01, filing windows
- `test_users.py` — all six roles (all opaque) + per-user-id builders for the segregation-of-duties tests
- `fixtures.py` — composite chain builders: `setup_lane`, `setup_cleared_hwb`, `setup_consolidated`, `setup_tendered`, `setup_delivered` (multi-waybill), `setup_delivered_claim`, `drive_shipper_to_suspended`, plus primitive steps
- `__init__.py` — barrel export

**`test_suite/`** (8 files): `conftest.py` + 7 test files — `test_01_platform_envelope_errors_listings.py` (9), `test_02_rbac_and_customs.py` (5), `test_03_screening_and_waybill_lifecycle.py` (11), `test_04_consolidation_rating_capacity.py` (26), `test_05_tender_and_milestones.py` (11), `test_06_cascades_and_conservation.py` (6), `test_07_claims.py` (11).

## Test count: 79 collected (pytest collection clean)

**Queue A (Difficulty): 36 tests, 18/18 instances covered (≥2 each).** Skipped: none.

**Queue B (Corner): 43 tests, 43/44 non-stub instances covered; 4 stubs correctly untranslated** (`liability_variant_math`, `charge_line_rounding_order`, `cascading_side_effects_layer`, `dual_variant_calculation_layer` — all four cross-references verified to resolve to real queue-A instances). Skipped: 1 —
- `entities/computed_charge_fields_input_ignored`: the PRD never states how the server treats client-supplied values for computed fields. A faithful PRD-only implementer could either ignore extra fields or reject the request as malformed; the outcome is not uniquely derivable, so the instance fails the two-condition filter and was left as a gap (not weakened, not skip-marked).

## Audit results

- **Stage 1**: `test_helpers` imports cleanly under the framework; 44 client methods; no scaffold/table references in comments or docstrings.
- **Stage 2 tag audit**: 79/79 tests carry exactly one `Design:` line; 0 unknown/dangling tags; 0 tags pointing at stub instances; queue A coverage ≥2 everywhere; queue B non-stub coverage ≥1 everywhere (except the one filtered instance above).
- **Stage 2 verbatim citation audit**: 118 quoted spans extracted from docstrings; all survive literal whitespace-normalized grep against `PRD.md` (14 initial failures — ellipses, markdown `**` markers, reformatted table rows — were fixed and re-verified).
- **No `skip`/`skipif`/`xfail` markers** anywhere; no freelance scaffold-walked tests.

Notable judgment calls within PRD-derivable bounds: the shipper-defaults test asserts `version` presence/type but not `== 1` (PRD pins increment-by-one, not the initial value); the EXCEPTION-milestone test drops the `out_of_order == false` assertion (PRD defines ranks only for DEPARTED/ARRIVED/DELIVERED); the design recipe's equal cutoff/departure timestamps in `default_clock_epoch_keeps_booking_open` were corrected to satisfy the PRD's "cutoff must be strictly earlier than departure" constraint while preserving the asserted behavior.

## Step 6: Generate Implementation — 2026-08-14T13:58:00.000Z

Implementation complete and verified. Summary:

## File inventory — `tasks/task_1735_air_freight_forwarding_consolidation/workspace/implementation/`

| File | Role |
|---|---|
| `start.sh` | Executable foreground launcher (see contract below) |
| `requirements.txt` | `flask>=3.0` |
| `app.py` | Entry point, blueprint registration (`/air-freight` prefix; clock route unprefixed), ApiError/404/405/500 handlers |
| `db.py` | In-memory `Store` (9 entity dicts + uniqueness indexes), logical clock (fixed default `2026-08-01T00:00:00Z`), monotonic `issue_ts()` for strictly-increasing `created_at` |
| `errors.py` | `ApiError` + all 30 catalog error IDs |
| `response.py` | Envelope helpers: `meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`, pagination fields in `meta` |
| `middleware.py` | `X-User-ID`/`X-User-Role` auth (6 declared roles), body validators, pagination params (`limit` 1–100 default 10, `offset` default 0) |
| `money.py` | Decimal math: ROUND_HALF_UP 2dp, 0.5 kg ceiling, DIM_FACTOR 0.006, spot threshold 85.0, SDR 22×1.35, demerit 3 |
| `timeutil.py` | ISO-8601 parse/format with 3 fractional digits |
| `services.py` | Serializers, lookups with per-entity 404s, rating pipeline, consumption/totals recompute, bubble-ups, cascades |
| `routes_*.py` (9 modules) | clock, shippers, rate_agreements, bookings, mawb, hwb, screening, customs, claims |

**Endpoint count: 40/40 implemented** (1 clock + 39 under `/air-freight`), matching the scaffold endpoint table exactly.

## Key architectural decisions

- **Storage model**: pure in-memory dicts keyed by UUID; empty on every boot (no seeding), so `per-test-server` restarts are clean. `version` starts at 1; every mutation (including cascade side effects) refreshes `updated_at` and bumps `version`. MilestoneEvents carry no `version`/`updated_at` per spec. `created_at` minted from the logical clock via a monotonic allocator (1 ms min step) so screening-record ordering always matches creation order — required by the latest-per-type clearance rule across resubmissions.
- **State machine enforcement**: all transitions gated with the exact scaffold error IDs in PRD §2.6 priority order (auth → role → existence → OCC `expected_master_waybill_version` 412 → state gates → DG → SoD → structural → lane → temporal → capacity/fiscal). Customs transition uses the per-`target_status` role map. OCC accepts int or numeric-string (test templates substitute versions as strings). Spot snapshot counts {CONSOLIDATED, TENDERED} candidate-excluded; booking consumption counts {CONSOLIDATED, TENDERED, IN_TRANSIT}; MAWB totals count {CONSOLIDATED, TENDERED} only — three deliberately different sets, implemented verbatim.
- **Calculation modules** (`money.py`/`services.py`): chargeable weight (ceil to 0.5 kg, QUOTED vs FINAL volume basis), IATA lowest-applicable-rate freight selection, pinned per-line-round-then-sum charge lines (verified: 3.33×45.5 kg + 15% fuel + 10.01 fee = 184.26, not 184.25), locked spot flag at inclusive 85.00 snapshot, STANDARD (2970.00 @ 100 kg) vs DECLARED_VALUE liability, inclusive ≥3 demerit suspension. Cascades: booking-cancel 3-link (void → detach/zero → recompute), screening-reject 3-link (reject → demerit → auto-suspend), milestone rank rule with `out_of_order` persistence (EXCEPTION records with `out_of_order=false`, never transitions), booking auto-DEPARTED bubble-up, eager + lazy cutoff auto-close.

## start.sh contract

Confirmed: reads `$PORT` (default 10000 via `app.py`), binds `0.0.0.0`, runs in **foreground** via `exec python3 app.py`, and the dependency install is guarded (`if ! python3 -c "import flask"`) so per-test reboots skip pip — cold boot measured at ~0.5 s.

## Verification

Two smoke suites (~110 assertions) run against fresh `start.sh` boots: full happy path (shipper → verify → agreement → booking → MAWB → HWB → screening → consolidate → measure → tender → milestones → delivery → claim → settle → close) plus error paths (all 30 error IDs exercised across both suites), boundary checks (exact 85.00% spot, exact-fill capacity, inclusive tier boundary, inclusive claim deadline, touching rate windows, 30-min tender buffer), priority-order checks (state-beats-safety, stale-version beats all), and both cascade chains. **All checks passed.**

## Step 7: Test/iterate loop — 2026-08-14T14:30:00.000Z

Iteration 1 (baseline sweep): 78/79 in 7 rounds, 77/79 in round 3. Union of failures: 2 tests.

**Failure A — `test_07_claims.py::TestClaimRequiresDelivered::test_claim_succeeds_after_delivery` (8/8 rounds, deterministic).** Asserted `delivered_at_utc == "2026-08-11T09:00:00Z"` (exact string). Implementation returns `"2026-08-11T09:00:00.000Z"`. STEP 1a: covered — PRD §3.6 "delivered_at_utc stamped from the milestone's event_time_utc". STEP 1b: exact lexical form NOT uniquely derivable — §2.4's three-fractional-digit rule is scoped to system-managed `created_at`/`updated_at`; nothing pins the serialization of the client-derived stamp, so verbatim-copy and parse-and-normalize implementations are both PRD-faithful. STEP 1c split applied: kept the covered instant-provenance assertion (compare parsed datetimes), dropped the uncovered string-form assertion. Test fix, no deletion, no implementation change.

**Failure B — `test_07_claims.py::TestLiabilityVariants::test_standard_liability_limit` (round 3 only, flaky).** `ConnectionError: RemoteDisconnected` on the test's FIRST request; zero server-side tracebacks. Root cause: the shared `requests.Session` pools a keep-alive connection to the server that per-test-server isolation SIGKILLs before the next test; urllib3's `is_connected` poll(0) probe is TOCTOU-racy, so a dead pooled socket is occasionally reused. Harness-level transport flake, fixed task-locally in `test_helpers/api_client.py`: `api_client.session.headers["Connection"] = "close"` forces a fresh TCP connection per request, eliminating the stale-connection class.

Iteration 2 (verification sweep): **79/79 in all 8 rounds (632/632). Clean.**

## Step 8: Finalize PRD — 2026-08-14T14:45:00.000Z

Done. Single minimal edit applied, diff verified.

## Summary

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_1735_air_freight_forwarding_consolidation/workspace/PRD_FINALIZED.md`

**Line counts / delta:** PRD.md 315 lines, PRD_FINALIZED.md 315 lines — 0% line-count delta (one in-place sentence insertion on line 215).

**Changes (1 total):**
- §3.6 (Transit milestones, line 215) — **insert** — added one sentence pinning that client-supplied timestamps the server stores and later returns (specifically the milestone's `event_time_utc` and the waybill's `delivered_at_utc` stamped from it) are echoed in normalized ISO 8601 UTC form with exactly three fractional digits (e.g., submitted `2026-08-11T09:00:00Z` → returned `2026-08-11T09:00:00.000Z`), instant unchanged — `implementation/routes_mawb.py:435` (stamp), `implementation/services.py:422` (`delivered_at_utc` serialization), `implementation/services.py:486` (`event_time_utc` serialization), `implementation/timeutil.py` (`iso()`).

This resolves the only behavioral item in `<step_7_diff>`: the test asserted verbatim lexical form of `delivered_at_utc`; the implementation parse-and-normalizes. PRD §3.6 pinned only instant provenance and §2.4's three-fractional-digit rule covers only system-managed `created_at`/`updated_at`, so the echo form was a two-reader divergence — now pinned to the implementation's behavior. The other Step 7 item (test_helpers `Connection: close` header) is a pure test-transport fix with no PRD behavioral content, so no PRD edit for it.

**Per-edit pre-edit search log (edit 1 of 1):**
- (a) **Subject:** lexical/serialization form of stored client-supplied timestamps when returned on the wire — specifically `delivered_at_utc`, with `event_time_utc` as the same-pattern sibling.
- (b) **Impl paths enumerated and grepped/read:** all `req_datetime`/`parse_iso` inputs (`middleware.py:158-162`; callers at `routes_bookings.py:31-32`, `routes_mawb.py:261-262,377`, `routes_rate_agreements.py:72-73`, `routes_clock.py:18`); all serialization sites (`services.py:365-366, 387-388, 422, 472-473, 486`; `routes_clock.py:24`); the DELIVERED transition (`routes_mawb.py:430-442`); the claim deadline consumer (`routes_claims.py:67`, datetime-typed, lexical-form-agnostic); HWB init (`routes_hwb.py:80`, `delivered_at_utc=None`); `timeutil.py` (`iso()` always emits exactly three fractional digits).
- (c) **Wording adjustment:** initial draft named only `event_time_utc`/`delivered_at_utc`; after the enumeration showed bookings, tender windows, rate-agreement validity, and the clock echo all use the identical `iso()` normalization, the sentence was restructured as a general rule ("Client-supplied timestamps that the server stores and later returns … are echoed in normalized ISO 8601 UTC form with exactly three fractional digits") with the two milestone-site fields named as the parenthetical instantiation — avoiding a false implication that normalization is milestone-specific while staying scoped to the Step 7 site.

## Step 9: Complete PRD — 2026-08-14T15:10:00.000Z

Done. `PRD_COMPLETED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_1735_air_freight_forwarding_consolidation/workspace/PRD_COMPLETED.md`.

**Source vs output:** `PRD_FINALIZED.md` (existed; used as source) 315 lines / 48,198 chars → `PRD_COMPLETED.md` 316 lines / 52,674 chars. Delta: +1 line, +4,476 chars. No sections added; all changes are in-paragraph inserts/revisions plus one lead-in paragraph inside existing §5.

**Counts:** 25 ambiguity-pins, 6 mismatch-revisions (31 distinct changes across 22 edit sites).

**Changes:**

- §2.2 — insert — ambiguity — pins which object multi-resource mutations return (consolidation/deconsolidation → the house waybill; clock → `{current_utc}`; all others → path-addressed resource) — routes_mawb.py:204,224; routes_clock.py:22; response.py:17-19
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; out-of-range values clamped (limit to [1,100], offset floored at 0) — middleware.py:184-208
- §2.3 — insert — ambiguity — `has_more` true iff `offset` + returned items < `total_count` — response.py:27
- §2.4 — revise — ambiguity — `version` starts at 1 on creation (was silent on initial value; OCC depends on it) — services.py:62
- §2.5 — insert — ambiguity — `expected_master_waybill_version` must be an integer (numeric string accepted); absent/unparseable → `ERR_INVALID_REQUEST` at the OCC pipeline position — middleware.py:167-181; routes_mawb.py:124-130
- §2.6 item 5 — insert — ambiguity — within the state-gate tier, checks apply in the order §3 pins per operation — routes_mawb.py:137-157, routes_customs.py:79-92
- §2.6 item 8 — revise — mismatch — dropped the duplicate "tender requires a consolidated waybill (`ERR_NO_CONSOLIDATED_HOUSE_WAYBILLS`)"; impl surfaces it at the state-gate tier (before malformed-input checks), as item 5 already lists — routes_mawb.py:247-253 vs 260-268
- §2.6 — insert — ambiguity — request-body contract: JSON object required where read, absent body = empty object, body ignored where no fields defined — middleware.py:68-75
- §2.7 — revise — mismatch — recompute trigger list made exhaustive (added the `DELIVERED` milestone; pinned that recording a measured volume does NOT recompute consumption, contra the prior general "any member's volume changes" clause) — routes_mawb.py:438-439; routes_hwb.py:190-206
- §2.9 — insert — ambiguity — clock-set accepts any instant (no monotonicity check); moving backward never reopens `CUTOFF_CLOSED` — routes_clock.py:16-22; services.py:123-127
- §2.9 — insert — ambiguity — logical clock sources all server timestamps (`created_at`, `updated_at`, `api_request_timestamp`); creation timestamps strictly increasing via 1 ms step — db.py:51-66; response.py:13
- §2.10 — revise — mismatch — demerit suspension fires at "at least" the threshold (impl uses `>= 3`, not "brings to 3") — services.py:331-334
- §3.1 — insert — ambiguity — weight-break tier values and all commercial terms (`min_charge_amount`, `fuel_surcharge_pct`, `security_fee_amount`, `spot_surcharge_pct`) must be non-negative, else `ERR_INVALID_REQUEST` — routes_rate_agreements.py:40-45,68-71
- §3.2 — insert — ambiguity — DEPARTED bubble-up is re-evaluated on every master-waybill state change (milestone transition, void, close) — routes_mawb.py:336,360,425,429,440; services.py:191-202
- §3.3 — revise — ambiguity — `pieces` pinned as positive integer (impl rejects non-integers) — middleware.py:103-109; routes_hwb.py:43
- §3.3 — insert — ambiguity — screening resolution: missing/empty `rejection_reason` on `REJECTED` → `ERR_INVALID_REQUEST`; a reason supplied with `CLEARED` is discarded — routes_screening.py:34-41
- §3.3 — revise — mismatch — suspension condition "reaches three" → "reaches or exceeds three" (an UNVERIFIED shipper can accumulate 3+ demerits before verification; the next rejection while KNOWN suspends) — services.py:332; routes_shippers.py:60-64
- §3.3 — insert — ambiguity — bubble-up acts only while the waybill is `SCREENING`; resolving a leftover PENDING record after recall updates the record with no transition/demerit — services.py:313-314
- §3.3 — insert — ambiguity — recall retains `submitted_by_user_id` until a re-submission overwrites it — routes_hwb.py:169-171
- §3.4 — insert — ambiguity — MAWB totals defined: count attached waybills in `CONSOLIDATED`/`TENDERED` only; `total_freight_amount` sums waybills' `total_charge_amount`; recomputed at consolidation/deconsolidation/tender/`DEPARTED` milestone, zeroed on void, not recomputed at measure — services.py:43,177-188; routes_mawb.py:423
- §3.4 — revise — mismatch — open check order reversed: from-state `ERR_INVALID_STATE` checked before booking-OPEN `ERR_BOOKING_NOT_OPEN` — routes_mawb.py:93-106
- §3.4 — revise — mismatch — consolidation bullet chain: removed the stale-version bullet from the post-gates chain (impl and §2.5 both evaluate OCC before all state gates; the bullet had it 4th, after the three state gates) — routes_mawb.py:124-157
- §3.6 — revise — ambiguity — tender lead-in pins MAWB from-state `ERR_INVALID_STATE` checked before the rest of the battery — routes_mawb.py:233-238
- §3.6 — insert — ambiguity — recorded `measured_volume_m3` must be > 0, else `ERR_INVALID_REQUEST` — routes_hwb.py:201
- §3.6 — insert — ambiguity — `exception_code` optional, defaults to `NONE`; `EXCEPTION` events always recorded with `out_of_order` false — routes_mawb.py:378,393-396
- §3.7 — insert — ambiguity — entry creation on a `CANCELLED` waybill pinned to `ERR_INVALID_STATE` — routes_customs.py:38-43
- §3.7 — insert — ambiguity — `rejection_reason` required non-empty on `REJECTED` (`ERR_INVALID_REQUEST`); retained through rework/later transitions until replaced; `broker_reference` recorded only on the transition to `FILED` — routes_customs.py:93-104
- §3.7 — insert — ambiguity — entry from-state gate checked before the handoff waybill-state requirement — routes_customs.py:79-92
- §3.8 — insert — ambiguity — optional `reason` on resolve-review is accepted but not persisted — routes_claims.py:123
- §4 — revise — ambiguity — house-waybill list filters are exact-match and combine conjunctively — routes_hwb.py:93-104
- §5 — insert — ambiguity — envelope-level errors: undeclared path/unsupported method → `ERR_NOT_FOUND` (404); unexpected fault → `ERR_INTERNAL` (500) — app.py:49-61

All endpoint tables, RBAC mappings, error catalog entries, rating formulas, state machines, cascades, and the validation-order skeleton were verified against the implementation and already matched; the changes above close the remaining silences and the six order/threshold mismatches.
