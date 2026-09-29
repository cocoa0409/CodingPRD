## Step 1: Create task directory — 2026-08-27T00:00:00.000Z

Created `tasks/task_2158_hospital_case_management/` and `tasks/task_2158_hospital_case_management/workspace/`. Index 2158 chosen as max existing (2157) + 1.

## Step 2: Generate scaffold — 2026-08-27T05:35:00.000Z

Done. Three scaffold artifacts generated purely from the scenario text plus the scaffold-generator spec (no sibling task was read, listed, or grepped).

## Files

| Path | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2158_hospital_case_management/SCAFFOLD.yaml` | 1970 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2158_hospital_case_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1635 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2158_hospital_case_management/SCAFFOLD_CORNER_DESIGN.yaml` | 3040 |

**Lint verdict (pasted verbatim):**
```
Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     50
  Calls scanned (§1.8+§1.9):  707

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Contents

- **§1.0 envelope** — FIXED block emitted verbatim. Profile: `multi_party_negotiation` + `compliance_audit`; topology `graph`; shape `parallel`; role model `segregation_of_duties`; layers = OCC, cascading side effects, dual-variant calc, selector policy. `api_prefix: ""` (flat top-level URLs).
- **§1.1 entities (12)** — Payer, Patient, Episode, RiskScreening, Barrier, PostAcuteProvider, NetworkContract (Payer×Provider junction), Referral, BedOffer, AuthorizationRequest, TransportVehicle, LogisticsOrder (polymorphic DME/transport). 19 FKs, all with the canonical `FK -> X.id` prefix and a reverse-reachability GET.
- **§1.2 state machines (8 blocks / 6 entities)** — Episode carries **two parallel axes** (`case_status` with a PLANNING<->READY cycle; `barrier_posture` compound over children); Barrier is cyclic (RESOLVED->OPEN); Referral is cyclic (negotiation rounds via rebroadcast); AuthorizationRequest is cyclic (appeal rounds, capped at 2); BedOffer and LogisticsOrder branch with divergent side-effect sets. **§1.2.1: 2 OCC rules** (`bed-offer-create-stale-referral` on Referral.version; `transport-order-create-stale-episode` on Episode.version), both 412.
- **§1.3 calculations (10)** — risk scoring (dual variant admission/predischarge), screening-derived barriers, posture rollup, avoidable-delay interval merge, placement cost projection (dual variant network/billed, per-day-then-sum rounding pinned), authorization award (discount tier pinned on pre-discount gross), bed-offer rank + selector (filter/rank/2 tie-breaks/empty fallback), bundle requirement, logistics cost, throughput metrics (7 numbered pinned steps).
- **§1.4 validations (35 rows)** — explicit integer priorities 1->71, spanning auth / existence / OCC / state / posture / safety / referential / temporal / constraint / fiscal.
- **§1.5 endpoints (49)** — full registry, episode lifecycle, screening, barrier, referral/offer negotiation, authorization, logistics, a throughput computed read, and one test-driving `POST /_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` startup default.
- **§1.6 errors (52)** — domain-specific; every one is triggered by at least one design instance (verified programmatically).
- **§1.7 roles (6)** — PlatformAdmin, CaseManager, UtilizationReviewNurse (all `opaque`), PayerRepresentative (`entity_backed:Payer`), PostAcuteLiaison (`entity_backed:PostAcuteProvider`), DischargeCoordinator (`opaque`); two four-eyes controls.
- **§1.8 — 18 instances** (9 rules x 2), all with executable `setup_api_calls` chains and literal asserts computed in Python (e.g. 1168790 vs the wrong 1168785; 500000/0.03/485000; risk 43<->50 at meds 9<->10; 78.0 delay union; O/E 1.056).
- **§1.9 — 57 instances** (50 with recipes + 7 `excluded_because` stubs) across all nine claim-extraction-guide sections.

Cross-file checks all pass: 75 unique instance names, zero unbound `${var}` placeholders, all stub references resolve to real §1.8 names, no forbidden concurrency vocabulary, and neither design key appears inside `SCAFFOLD.yaml`.

## Step 3: Copy shared files — 2026-08-27T05:35:10.000Z

Copied `INSTRUCTION.md` to `tasks/task_2158_hospital_case_management/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-27T05:52:00.000Z

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2158_hospital_case_management/workspace/PRD.md` — **394 lines**.

Withhold constraint honored: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced. Only `SCAFFOLD.yaml`, the skill spec, and the canonical §2.2 file were read.

## Structure
§1 Introduction (3 paras) · §2 with 10 subsections (2.2 byte-verbatim, machine-verified) · §3 with 9 domain-grouped subsections · §4 endpoint table (4 cols) · §5 error table (2 cols). Ends at §5 — no audit footer.

## Coverage confirmation

- **12 entities** — all field names present: 124/124 entity fields verbatim in backticks. Payer/Patient/Episode (§3.1–3.2), RiskScreening (§3.2), Barrier (§3.3), PostAcuteProvider/NetworkContract (§3.1), Referral/BedOffer (§3.4–3.5), AuthorizationRequest (§3.6), TransportVehicle/LogisticsOrder (§3.1, §3.7).
- **8 state-machine blocks** — Episode `case_status` (§3.2, §3.8), Episode `barrier_posture` (all 6 posture transitions, §3.3), RiskScreening (§3.2), Barrier cyclic loop (§3.3), Referral negotiation cycle (§3.4), BedOffer 4-way branch (§3.4–3.5), AuthorizationRequest appeal cycle + expiry (§3.6), LogisticsOrder branch + compensation (§3.7).
- **10 calculations** — composite risk (both variants, all 12 constants), screening barrier derivation (S1/S2 + dedup + ordering), posture rollup (72h inclusive), avoidable-delay interval union (sort/merge/round order), placement cost projection (per-day rounding pinned before summing), authorization award (3 pinned steps, tier keyed on pre-discount gross), bed-offer rank + selector with both tie-breaks, readmission bundle requirement, logistics cost (all 5 DME rates), throughput metrics (7 pinned steps, 4 acuity multipliers, 4 grade bands).
- **35 validations** — every `error_id` matchable to its condition in prose; priority ladder stated normatively in §2.8, with per-endpoint orderings restated at mark-ready (state → posture → barriers → bundle → placement), discharge (state → posture → segregation → logistics), and document-choice (attestation strictly before both coverage gates). All `applies_to` scopes enumerated.
- **49 endpoints** — table has exactly 51 rows (49 + header/separator); all query params, path params and request-body identifiers appear in prose (81/81).
- **52 errors** — table has exactly 54 rows; all 52 also appear in §2/§3 narrative, none introduced only in §5.
- **6 roles** — `PlatformAdmin`, `CaseManager`, `UtilizationReviewNurse`, `PayerRepresentative`, `PostAcuteLiaison`, `DischargeCoordinator`, each individually named with its `identity:` translated (two entity-backed, four opaque).

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 124 required, 124 present, 0 missing
- endpoints[].request_body/input: 81 required, 81 present, 0 missing
- endpoints[].query_params/path_params: included above, 0 missing
- endpoints[].output dict fields: 10 required, 10 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 35 checked, 35 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_referral_version / expected_episode_version + ERR_STALE_REFERRAL_VERSION / ERR_STALE_EPISODE_VERSION + HTTP 412 all named), 0 missing
- state_machines[].transitions: 8 blocks / 43 transitions checked, 43 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 35 checked, 35 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 49 checked, 49 expressed, 0 missing
- entities[].fields[] structured content: 124 checked, 124 reconstructible from prose, 0 missing
- sibling-branch symmetry: 5 groups checked (APPROVED/PARTIALLY_APPROVED, NETWORK_RATE/BILLED_RATE x2 calcs, ADMISSION/PREDISCHARGE variant, PATIENT_TRANSPORT/DME_DELIVERY, 4 BedOffer exits), 5 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 977
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

One judgment call worth flagging: the scaffold's `case_status` table declares `→ CANCELLED` rows from `ADMITTED`, `SCREENED` and `PLANNING`, while the revert endpoint's description also lists `READY_FOR_DISCHARGE` as a cancellable state. §3.8 states all four, with the `ADMITTED` variant's narrower cascade (barrier waiving only) called out separately — so neither source is contradicted.

## Step 6: Generate implementation — 2026-08-27T06:22:00.000Z

The implementation is complete and verified.

## Files written (`workspace/implementation/`, 2870 lines total)

| File | Lines | Role |
|---|---|---|
| `app.py` | 84 | Flask entry point, blueprint registration, global error handler, auth `before_request`, request-serializing WSGI lock, `0.0.0.0:$PORT` |
| `store.py` | 151 | In-memory dicts, logical clock (`2026-08-01T00:00:00Z` default), UUID/timestamp minting, `touch()` |
| `errors.py` | 72 | `ApiError` + the 52-entry error->HTTP catalogue |
| `envelope.py` | 95 | `meta`/`response_type`/`data` envelope, `req_` request ids, pagination (`limit`/`offset`/`total_count`/`has_more`) |
| `validate.py` | 241 | Auth headers, RBAC, typed body readers (all raise `ERR_VALIDATION`), every enum vocabulary |
| `calc.py` | 261 | 10 calculations, all constants, `Decimal` + `ROUND_HALF_UP` throughout |
| `derive.py` | 550 | Lookups, lazy sweeps, derived fields/ledgers, 12 serializers |
| `cascade.py` | 122 | Revert, cancel, discharge, denial cascade, barrier reopen/close |
| `routes_registry.py` | 243 | Clock, payers, patients, providers, contracts, vehicles (16 endpoints) |
| `routes_episode.py` | 188 | Episode lifecycle + throughput (8) |
| `routes_clinical.py` | 181 | Screenings + barriers (6) |
| `routes_placement.py` | 314 | Referrals + bed offers (9) |
| `routes_authorization.py` | 166 | Authorizations (5) |
| `routes_logistics.py` | 191 | Logistics orders (5) |
| `start.sh` / `requirements.txt` | 10 / 1 | Guarded install, `exec python3 app.py` |

## Verification

- **Routes**: programmatic diff of `app.url_map` against the PRD §4 table — **49 registered, 0 missing, 0 extra**.
- **Errors**: AST/regex sweep of all modules against `ERROR_HTTP` — **all 52 error ids are raised somewhere; no unknown ids used**.
- **Compilation**: `python -m py_compile *.py` clean; AST scan confirms every route handler returns a response (no truncated bodies).
- **Boot**: `bash start.sh` serves HTTP in ~560 ms; a kill-and-relaunch on the same port returns `total_count: 0` for every collection — **no state, no seeding, no disk artifacts**.
- **Behaviour**: three smoke suites (~180 assertions) all pass with 0 failures, covering the risk score (82 admission -> 76 predischarge), derived barriers in rule order with strictly ascending `created_at`, posture CLEAR/ACTIVE/ESCALATED incl. the inclusive 72 h boundary, the delay-union (6.0 h, zero-length reopen, waiver erasure), tiered placement projection (network 970000 / billed 909375), rank score, `recommended_bed_offer_id`, half-open bed holds (overlap vs back-to-back), fairness/breadth/round-open, both OCC guards (412), the award tiering (1000000 -> 0.03 -> 970000), pend/deny/appeal-limit/partial/expiry with ledger conservation, superseding transport, 45-min buffered vehicle conflict, delivery-after-needed-by, both four-eyes controls, revert/AMA cancel/discharge cascades, and throughput grading.

## Validation-ladder approach

Each handler runs the ladder explicitly, in the fixed §2.8 precedence, rather than relying on framework ordering: `authenticate()` in `before_request` -> `require_roles()` -> entity-backed identity resolution (`ERR_NOT_OWNER`, only on the three declared endpoints, before path resolution) -> left-to-right path existence -> resource ownership compare -> body well-formedness -> body-referenced FK existence -> uniqueness -> OCC -> state admissibility -> safety -> referential -> temporal -> constraint -> fiscal. Numeric `validations[].priority` was used as the tiebreak everywhere the PRD prose is silent; where the PRD pins a different order it wins — notably `ERR_INSUFFICIENT_PROVIDER_CHOICE` **before** `ERR_REFERRAL_FAIRNESS_VIOLATION` (§3.4), `ERR_WAIVER_ROLE_REQUIRED` **before** `ERR_SEGREGATION_OF_DUTIES` (§2.10), and document-choice's referral-state -> offer-resolution -> offer-state -> attestation -> coverage chain (§3.5) overriding the generic body-existence-before-state rule.

Two judgement calls worth flagging: `Episode.version` bumps on **every** mutation of the episode row (per §2.4's unconditional rule), including the `SCREENED -> PLANNING` planning-artifact transition, which the scaffold's per-endpoint `side_effects` list does not enumerate; and clock-derived instants (`clock_start_at`, `submitted_at`, `decided_at`, `marked_ready_at`, `discharged_at`, `current_utc`) echo the exact string the clock was set with, while computed instants (`expires_at`) use the canonical three-fractional-digit form.

## Step 5: Generate unit tests — 2026-08-27T06:40:00.000Z

All verification passes. Final state:

## Files written

**`test_helpers/`** (1,876 lines)

| file | lines |
|---|---|
| `__init__.py` | 27 |
| `api_client.py` | 217 (49 endpoint methods + `get_raw` for the header-less auth probe) |
| `api_errors.py` | 118 (51 error ids, registered with the framework status map) |
| `assertions.py` | 301 (12 per-entity assertions + `avoidable` derivation, acceptance-rate, gross-split, envelope invariants) |
| `constants.py` | 85 |
| `factories.py` | 175 |
| `fixtures.py` | 374 (5 tiers: primitives -> screened/planning episode -> broadcast/choice-pending/placed referral -> authorization -> logistics -> ready/discharge) |
| `test_users.py` | 87 (opaque-role constants + `make_payer_rep_headers` / `make_liaison_headers` for the two `entity_backed` roles) |
| `types.py` | 492 |

**`test_suite/`** (4,398 lines, 86 tests): `conftest.py` 59; `test_01_operational_registry.py` 414; `test_02_risk_screening_and_scoring.py` 333; `test_03_barriers_and_delay_accounting.py` 371; `test_04_placement_broadcast_and_fairness.py` 357; `test_05_bed_offers_and_holds.py` 366; `test_06_offer_ranking_and_cost_projection.py` 360; `test_07_documenting_patient_choice.py` 485; `test_08_authorization_lifecycle.py` 351; `test_09_logistics_orders.py` 544; `test_10_readiness_and_discharge.py` 293; `test_11_roles_and_segregation_of_duties.py` 289; `test_12_optimistic_concurrency.py` 176.

## Coverage

- **Queue A (Difficulty): 36 tests** — all 18 instances across the 9 rules have exactly 2 tests each.
- **Queue B (Corner): 50 tests** — all 50 non-stub instances have 1 test each.
- **7 `excluded_because:` stubs not translated**; every `difficulty_instance` cross-reference was checked and resolves to a real §1.8 `name:`.

## Skipped instances

**None.** Every instance passed the PRD-first two-condition filter. Two assertion-level narrowings were applied inside otherwise-complete tests, under the Silence-pattern rules:

1. `Corner/calculations/dme_order_cost_uses_item_rate_constant_not_vehicle_rates` — dropped the recipe's `vehicle_id == null and mileage_miles == null` sub-assertion. PRD §3.7 says a `DME_DELIVERY` order "must not carry `vehicle_id` or `mileage_miles`" (an input rule) but never pins whether the serializer emits them as explicit nulls (`default-value` / `computed-field` silence). Cost, status, ledger and `case_status` are asserted exactly.
2. `Corner/errors/offer_rejections_for_broadcast_membership_and_bed_unit` — the HOME_HEALTH probe simultaneously violates the provider-type guard and the bed-unit guard (its `bed_unit_codes` is `[]`), and PRD §3.4 lists the "four referential guards" without declaring their order normative. That one probe uses `validate_error_is_one_of([ERR_PROVIDER_TYPE_MISMATCH, ERR_UNKNOWN_BED_UNIT])` plus an HTTP-422 check (`error-precedence` silence). The other two probes assert exact error ids.

## Audits (all green)

- `ast.parse` clean on all 22 `.py` files; every file ends with a complete function and a trailing newline; `pytest --collect-only` = **86 tests collected**.
- `pyflakes` clean on `test_suite/` and `fixtures.py` (no undefined names, no unused imports).
- **Every test carries exactly one `Design:` line**, it is the last line of the docstring, and it resolves to a real instance `name:` — 0 untagged, 0 dual-tagged, 0 dangling.
- **188 PRD citations checked**; every one survives a whitespace-normalized literal match against `workspace/PRD.md` and is >=8 words. (Two citations were corrected during the sweep: `"When that set is non-empty..."` -> `"When the set is non-empty..."` and a stray leading `"And from \`RESOLVED\`..."`.)
- No `pytest.mark.skip` / `skipif` / `xfail` anywhere; no "scaffold" / "Table N" / "§1.x" references leaked into generated code or docstrings.

## Step 7: Run tests and iterate — 2026-08-27T06:52:00.000Z

All 8 parallel rounds pass 86/86. Exiting.

## Summary

**Iterations run:** 2 (baseline sweep -> one implementation fix -> clean sweep).

**Tests deleted:** none. Every failing test passed both STEP 1a (PRD verbatim coverage) and STEP 1b (unique derivability).

**Fixes applied to `test_helpers/`:** none — no fixture, factory, or role-header helper was inconsistent with the PRD.

**Fixes applied to `implementation/`:**

Baseline was a stable 80/86 across all 8 rounds — no flakiness; all six failures were one deterministic root cause. Every one tripped the same shape of assertion:

```
assert '2026-08-01T00:00:00Z' == '2026-08-01T00:00:00.000Z'
```

on `clock_stop_at`, `clock_start_at`, `marked_ready_at`, and `discharged_at`. The server was writing these fields with `db.now_raw()` — the logical clock echoed back **verbatim as the PlatformAdmin spelled it** — rather than rendering the instant in the document's declared timestamp format.

Diagnosis (STEP 1b): PRD §2.4 pins the house rendering for server-minted timestamps as "an ISO 8601 UTC timestamp with three fractional digits", and §2.2 says the same for `api_request_timestamp`. §2.6's "it reads exactly `2026-08-01T00:00:00Z`" fixes *which instant* the clock defaults to, not the serialization of every field derived from it — and the raw-echo reading is not merely an alternative but actually unsound, since an operator supplying `2026-08-03T05:00:00+02:00` would have that non-UTC string land verbatim in `clock_stop_at`, violating §2.4 outright. The artifact confirms the intended reading internally: `expires_at` (also server-minted from the clock, §3.6) was already rendered with `fmt_dt` and its exact-string assertion was passing all along. So the six tests are faithful and the implementation was inconsistent with itself.

- `workspace/implementation/store.py` — added `Store.now_iso()`, returning `fmt_dt(self.clock)`, so any field recording "the logical clock instant" renders in the §2.4 format independent of how the clock was spelled when set.
- `workspace/implementation/derive.py` (`make_barrier`, `close_barrier`), `cascade.py` (`reopen_barrier`, `cancel_episode`, `discharge_episode`), `routes_clinical.py` (`submit_screening`), `routes_episode.py` (`mark_ready`), `routes_authorization.py` (`decide`) — switched the eight row-field writes from `db.now_raw()` to `db.now_iso()`.

`routes_registry.py`'s `current_utc` response was deliberately left on `now_raw()`: §2.6 states the clock's own reading as `2026-08-01T00:00:00Z` literally, and that is the one place the PRD pins a clock rendering directly. No test constrains it either way.

No assertion was weakened, no skip/xfail added, no PRD-required check removed, and no endpoint, field, or side effect was added that does not trace to PRD prose. Storage remains in-memory dicts with nothing seeded at startup.

## Step 8: Finalize PRD — 2026-08-27T07:02:00.000Z

`PRD_FINALIZED.md` is written.

## Line counts
- `PRD.md`: 394 lines; `PRD_FINALIZED.md`: 394 lines — **0.0% line delta** (one paragraph extended in place, +2 sentences / ~600 chars).

## Changes
- **§2.6 The Logical Clock** — *insert* — pinned two things the PRD left open and that `<step_7_diff>`'s only implementation fix turned on: (a) the clock endpoint's `current_utc` echoes the operator's `to_iso8601` string verbatim; (b) every **row field** that records the logical clock instant, or an instant derived from it, is rendered as an ISO 8601 UTC timestamp with three fractional digits — the same rendering as `created_at` — regardless of how the clock was spelled. Fields named exhaustively. — `implementation/store.py:91-97` (`Store.now_iso`), `implementation/routes_registry.py:30` (`now_raw` for `current_utc`).

No other edit. The Step 7 diff lists no test deletions and no `test_helpers/` fixes, so nothing else traced to a PRD silence or mismatch.

## Pre-edit search log

**Edit 1 — §2.6 clock-instant rendering**

(a) **Subject identified:** how an instant taken from the logical clock is serialized when it lands in a persisted field, versus when it is reported back as the clock's own reading.

(b) **Impl paths enumerated** (grepped `now_raw|now_iso|fmt_dt|clock_raw|_at"]|req_dt` across all of `implementation/`, then read each site):
- `store.py:78-101` — `clock` / `clock_raw` pair, `now()`, `now_raw()`, `now_iso()`, `set_clock()`; `store.py:49` `fmt_dt`; `store.py:109-120` `wall_now_iso` (used only for `created_at`/`updated_at` via `base_row`/`touch` — wall clock, **not** the logical clock, so deliberately excluded from the sentence's scope).
- Clock-derived row writes (all `now_iso`): `derive.py:133` (`make_barrier` -> `clock_start_at`), `derive.py:159` (`close_barrier` -> `clock_stop_at`, reached by RESOLVED **and** WAIVED, and by the auth-approval, choice-cascade, discharge and AMA-cancel paths), `cascade.py:120` (`reopen_barrier` -> `clock_start_at`), `cascade.py:64` (`cancel_episode` -> `discharged_at`), `cascade.py:86` (`discharge_episode` -> `discharged_at`), `routes_clinical.py:96` (`submit_screening` -> `submitted_at`), `routes_episode.py:125` (`mark_ready` -> `marked_ready_at`), `routes_authorization.py:98-114` (`decide` -> `decided_at` on all four decisions) and `routes_authorization.py:107` (`expires_at` = `fmt_dt(clock + auth_expiry_days)` — the "instant derived from it" case).
- Off-Step-7 parallel endpoint: `routes_registry.py:22-30` — `current_utc` returns `db.now_raw()`, i.e. the raw echo, which my first sentence had to state explicitly rather than let the second sentence swallow.
- Client-supplied instants, checked so the sentence would not wrongly capture them: `routes_episode.py:30-41` (`admitted_at`), `routes_placement.py:32-40` (`needed_by`), `routes_placement.py:153-196` (`bed_available_from`, `hold_expires_at`), `routes_logistics.py:37-98` (`window_start`, `window_end`) — all stored as the `_raw` string from `validate.req_dt` and echoed unchanged by `derive.py` serializers (`ser_episode`, `ser_referral`, `ser_offer`, `ser_order`). Also `patients.date_of_birth` (a client-supplied calendar date).
- Serializer sweep (`derive.py:395-549`) to confirm the named field list is the complete set of server-minted timestamp fields across all twelve resources.

(c) **Wording adjustment made:** two. First, an early draft read "server-minted timestamps are rendered..." — that universal would have mis-described `routes_registry.py:30`'s `current_utc`, so the raw-echo case was split out into its own leading sentence before the general rule. Second, the general rule was re-scoped from "timestamp fields" to "wherever a **row field** records the logical clock instant, or an instant derived from it", with the fields named exhaustively — this keeps the eight client-supplied instants (`admitted_at`, `needed_by`, `bed_available_from`, `hold_expires_at`, `window_start`, `window_end`) and the wall-clock `created_at`/`updated_at` outside the claim, since none of them is written from the logical clock and all six client ones are echoed verbatim.

## Step 9: Complete PRD — 2026-08-27T07:12:00.000Z

Done. `PRD_COMPLETED.md` is written and verified structurally intact.

**Source vs output** — `PRD_FINALIZED.md` (present, so used as the base): 394 lines / 88,496 chars -> `PRD_COMPLETED.md`: 394 lines / 96,106 chars, **+7,610 chars**. Line count is identical because every change is an in-paragraph insert or revision; all 27 headings and all 105 table rows are byte-identical, verified by diff.

**Counts** — 39 edits across 31 paragraphs: **33 ambiguity-pins**, **6 mismatch-revisions**.

### Mismatch revisions
- §3.2 — revise — mismatch — "The episode adopts the submitting screening's figures" replaced: episode risk is re-derived on every read from the latest `SUBMITTED` screening with live barrier count/placement credit, so it can drift from the screening's frozen score — `derive.py:274-294`, `derive.py:470-472`
- §3.4 — revise — mismatch — rebroadcast credits **every** distinct provider on the new slate, not only "newly listed" ones — `routes_placement.py:107-112`
- §3.4 — revise — mismatch — `ERR_INVALID_INTERVAL` on a bed offer is tested *after* the four referential guards and the suspension check, with the overlap check last — `routes_placement.py:163-187`
- §3.5 — revise — mismatch — "that same authorization's `approved_days`" -> any one of the live authorizations may satisfy the day-count gate — `routes_placement.py:261-276`
- §3.7 — revise — mismatch — the DME supplier-type check runs *before* the shape check, and both before the interval test — `routes_logistics.py:50-76`
- §3.2 — revise — mismatch — `drg_gmlos_days` "carried to at most two decimals" is convention only; just `> 0` is enforced — `routes_episode.py:28`

### Ambiguity pins (grouped)
- §2.3 — insert — negative / non-integer `limit`/`offset` -> `ERR_VALIDATION` — `envelope.py:63-76`
- §2.4 — insert — `created_at`/`updated_at`/`api_request_timestamp` come from the host wall clock (not the logical clock), forced >=1 ms apart — `store.py:109-120`
- §2.6 — insert — client-supplied instants stored/echoed verbatim, parsed only for comparison — `routes_episode.py:41`, `routes_placement.py:195-196`
- §2.7 — insert — only `offers_received_count` is stored; the other four provider figures plus `logistics_committed_cents` / `authorized_days_total` are re-summed per read — `derive.py:297-307,424-441`
- §2.10 — insert — barrier transition admissibility precedes both waiver checks — `routes_clinical.py:151-160`
- §3.1 — insert x3 — `auth_expiry_days >= 1`; provider-suspend and vehicle-out-of-service are unguarded and idempotent — `routes_registry.py:44,157-163,237-243`
- §3.2 — insert x2 — draft screening's null fields, no episode gate, not a planning artifact; submit tests `DRAFT` first then episode state as `ERR_INVALID_EPISODE_STATE` — `routes_clinical.py:28-73`
- §3.3 — insert x3 — barrier create ungated by `case_status`; `note` validated but never stored/echoed; a waived barrier keeps its `accrued_delay_minutes` — `routes_clinical.py:127-149`, `derive.py:152-161,504-510`
- §3.4 — insert x6 — full broadcast check order (not-found -> referral state -> episode state -> breadth -> fairness -> suspension -> round-still-open); duplicate slate entries credited once; broadcast admitted only from `DRAFT`/`CHOICE_PENDING`, rebroadcast skips the episode gate; offers admitted only from `BROADCAST`/`CHOICE_PENDING`; unresolvable liaison id -> `ERR_NOT_OWNER` ahead of path resolution; referral create ungated — `routes_placement.py:25-101,144-168`
- §3.5 — insert x2 — non-boolean `patient_choice_attested` -> `ERR_CHOICE_NOT_ATTESTED`; document-choice returns the `Referral` — `routes_placement.py:235-249,292`
- §3.6 — insert x4 — new request's award-field initial values; unresolvable payer id -> `ERR_NOT_OWNER`; decision shape/range errors are `ERR_VALIDATION` tested before the status check, and `PEND` from `PENDED` is a state error; denial hop 2 reopens the most recent `RESOLVED` barrier and an already-`OPEN` one does not suppress a new row — `routes_authorization.py:47-96`, `cascade.py:292-300`
- §3.7 — insert x3 — confirm tests order state first then episode state (`ERR_INVALID_EPISODE_STATE`); reserved/omitted `reason_code` -> `ERR_VALIDATION` and cancel is ungated; order create ungated with `version` always advancing — `routes_logistics.py:104-120,166`
- §3.8 — insert x3 — readmission-bundle ungated and always bumps `version`; non-AMA revert outside `READY_FOR_DISCHARGE` -> `ERR_INVALID_EPISODE_STATE`; AMA from a terminal state likewise — `routes_episode.py:78-147`
- §3.9 — insert — the throughput report's `data` is exactly those nine keys, and the same derived figures also ride on every `Episode` representation — `routes_episode.py:178-188`, `derive.py:459-483`

Note: only `PRD_FINALIZED.md`, `implementation/`, and `INSTRUCTION.md` were read; `SCAFFOLD*.yaml` and `worklog.md` were not opened.
