# Worklog — task_2254_bond_movement_bonded_carrier_operations

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2254_bond_movement_bonded_carrier_operations/` and `tasks/task_2254_bond_movement_bonded_carrier_operations/workspace/`.

## Step 2: Generate scaffold — 2026-09-01T12:24:53.000Z

All three scaffold artifacts for task 2254 are complete and jointly lint-clean.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2254_bond_movement_bonded_carrier_operations/`)
- `SCAFFOLD.yaml` — 3,070 lines, §1.0–§1.7 only (top-level keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles; neither design key present).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1,516 lines, single key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4,155 lines, single key `scaffold_corner_design`.

**Scaffold profile** — `domain_name: in-bond-movement-bonded-carrier-ops`, `api_prefix: /in-bond`; entity_topology flat, state_machine_shape parallel, role_model segregation_of_duties, consistency_model immediate, complexity_layers = optimistic_concurrency, cascading_side_effects, rate_threshold_triggers, selector_policy.

**Counts**
- Entities: **12** (Port, BondedCarrier, CustomsBond, InBondMovement, SealEvent, ExaminationHold, AmendmentRequest, MovementReport, LiquidatedDamagesClaim, MitigationPetition, BondObligationLedgerEntry, ComplianceSweep; the last three plus SealEvent are immutable records with `common_fields: false`).
- State machines: **9** (including InBondMovement's two parallel dimensions `transit_status` and `custody_status`) plus **2** §1.2.1 concurrency rules.
- Calculation rules: **10** (bond obligation, transit allowance/deadline with sanction throttle, overdue measure, LD assessment, sanction points with a 4-bucket decay curve, mitigation waterfall with fee tiers and dual round variants, ledger balance, exam-window interval merge, general-order timeline, bond selector policy).
- Validations: **55** across priority bands 1–14; Endpoints: **41**; Error catalog: **55** codes; Roles: **4** (BondedCarrier, CBPOfficer, FPFOfficer, SuretyAgent).
- §1.8 difficulty design: **9 rule_ids / 18 instances** (2 per rule).
- §1.9 corner design: **79 entries across all 9 guide sections** — 63 full test recipes + 16 `excluded_because` stubs (entities 11, state_machines 8+3, calculations 7+5, validations 8+1, endpoints 5, errors 14+6, rbac 6, cross_cutting 3+1, consistency_model 1).

**Verification**
- `scaffold_lint.py` → `VERDICT: clean lint` (41 endpoints, 12 entities, 18 §1.8 + 63 §1.9 instances, **775 calls** all conforming to §1.5; all §1.1 FKs reverse-reachable).
- Instance names unique across both design files (0 duplicates); every stub cites an existing §1.8 instance name; every entry has exactly one of `test_recipe` / `excluded_because`.
- Error-catalog closure verified both ways: all 55 codes are triggered or stub-attributed in §1.8/§1.9, and no design file references a code outside the catalog.
- Hard constraint honored — nothing outside this task directory and the scaffold-generator skill was read.

## Step 3: Copy shared files — 2026-09-01T12:24:53.000Z

Copied `INSTRUCTION.md` to `tasks/task_2254_bond_movement_bonded_carrier_operations/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T13:00:00.000Z

PRD generated and verified.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2254_bond_movement_bonded_carrier_operations/workspace/PRD.md` — **426 lines**

## Sections covered

**§1 Introduction** — 3 paragraphs framing in-bond custody, the three design pressures (dual lifecycles, replay-derived bond exposure, segregation of duties), and the logical clock.

**§2 Global Specifications** — 11 subsections: 2.1 RBAC (4 roles, `X-User-ID`/`X-User-Role`, three distinct identity-binding models, segregation of duties); 2.2 Response Structure (pasted byte-for-byte from `section-2.2-response-structure.md`, verified verbatim); 2.3 Pagination (incl. the four non-default sort orders); 2.4 Identity, audit fields and the logical clock (the three `common_fields: false` entities documented as `id` + `created_at` only); 2.5 Money/day/rounding discipline; 2.6 The Bond Obligation Ledger; 2.7 The two status dimensions; 2.8 Cascades and version semantics; 2.9 Stale-version protection; 2.10 The fourteen ordered validation bands; 2.11 Nested-read path resolution.

**§3 Business Logic** — 7 workflow subsections: participants registration, movement filing (obligation formula, transit allowance, bond selection, STB window, fiscal gate), sealing/departure/chain of custody, diversion and extension requests, arrival/exportation/cargo release, examination holds + general order + compliance sweep, liquidated damages + mitigation petitions + sanction posture.

**§4** 41-row endpoint table, exactly 4 columns. **§5** 55-row error table, exactly 2 columns. Document ends at the §5 table with no footer.

## Hard Contract results

- **Contract 1 (Field-Name Coverage): PASS** — 116 unique identifiers from `entities[].fields[].name` plus all endpoint `input`/`query_params`/`path_params` keys; 0 missing. Two verification passes run (first pass flagged 36 apparent gaps that were all optional-marker `?` suffixes on already-present names).
- **Contract 2 (Rule Coverage): PASS** — 55/55 error IDs present in prose and in §5 with HTTP statuses cross-checked against the scaffold (0 mismatches); all 30 state names and all 63 declared transitions covered; all 41 endpoints in §4; all 60 endpoint `side_effects` narrated; all 10 calculations and both `concurrency_rules` covered; validation `priority` ordering stated as an explicit 14-band ordered list with the two invertible orderings (bond-activity before bond-sufficiency; seal integrity before temporal) called out.
- **Contract 3 (§3 Path Purity): PASS** — 0 backticked tokens in §3 start with `/`, are a bare HTTP method, or combine method+path; also 0 unbackticked `/in-bond` or verb+path mentions in §3.

## Coverage notes

1. **Header-name discrepancy resolved in favour of the skill.** The scaffold's validation band 1 names the role header `X-Role`; `SKILL.md` fixes the cross-task contract as exactly `X-User-ID` and `X-User-Role` (confirmed by `example-prd.md`). The PRD uses `X-User-Role`. Flagging in case the test generator reads the scaffold's spelling instead.
2. **`prior_violation_count` has two non-identical definitions in the scaffold** — the `MitigationPetition` field description adds a 365-day window that the `mitigation_offer_amount` input clause omits, and the two differ on "other claims" vs. "claims on other movements". The PRD states the conjunction of both restrictions.
3. **`package_discrepancy`**: the endpoint `side_effects` line renders it as a boolean comparison while the entity field defines it as `package_count − packages_reported`. The PRD uses the entity's integer-difference definition.
4. **Eleven fractional constants** (mitigation credits, round caps, decay factors, `PRIOR_VIOLATION_DEBIT`, `SANCTION_THROTTLE_FACTOR`, `PARTIAL_GRANT_FACTOR`) are expressed in unambiguous words ("twenty hundredths", "three quarters", "halved and rounded down") rather than as decimal literals, per the skill's no-pseudocode mandate. All other 40 constants appear as literals.
5. The two withheld design files were not opened, grepped, or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-01T14:32:08.000Z

Done. The suite is complete.

## Files created

**Stage 1 — `test_helpers/`** (9 modules): `__init__.py`, `constants.py`, `api_errors.py` (55 `ERR_*` codes + `set_error_http_status_map`), `types.py`, `test_users.py`, `api_client.py` (41 endpoints), `factories.py`, `assertions.py` (domain assertion helpers), `fixtures.py` (`World` + 17 precondition builders).

**Stage 2 — `test_suite/`**: `conftest.py` plus 18 test modules.
- Queue A (depth): `test_01_deadline_and_offer_variants.py` … `test_09_compensating_invariants.py` — 4 tests each, **36 tests**.
- Queue B (breadth): `test_10_entities.py` (16), `test_11_state_machines.py` (8), `test_12_calculations.py` (7), `test_13_validations.py` (8), `test_14_endpoints.py` (5), `test_15_errors.py` (14), `test_16_rbac.py` (6), `test_17_cross_cutting_layers.py` (3), `test_18_consistency_model.py` (1) — **68 tests**.

**Total: 104 tests in 18 files.**

## Instances translated vs skipped

- §1.8 difficulty: **18/18** non-stub instances translated, 2 tests each (36 tests).
- §1.9 corner: **63/63** non-stub instances translated (68 tests); the **16 `excluded_because:` stubs** were correctly never translated.
- **Zero instances skipped** — every non-stub instance passed the PRD-first two-condition filter. No placeholders, no skip/xfail.

## Verification passes (all green)

- `py_compile` clean on every file; `pyflakes` clean (only the intentional `noqa: F401` re-export in `conftest.py`).
- Every test carries exactly one `Design:` line as the last docstring line; **104 tests / 104 tags**, each tag's `<instance.name>` present verbatim in its source yaml.
- Every `PRD: "..."` citation survives a literal grep against `workspace/PRD.md` — **0 bad quotes** across all 18 files.

## Four design-vs-PRD conflicts resolved PRD-first

1. `custody_and_transit_dimensions_advance_independently` (difficulty) asserts `go_deadline 2026-08-30` / `go_grace_applied true`, but its hold opens while `IN_TRANSIT` and PRD §3.6 grants the one-time grace only for a hold opening while `ARRIVED`. `test_03` asserts the PRD-derived `2026-08-25` / `false`.
2. `arrival_report_records_port_discrepancy_and_go_deadline` (corner) asserts `package_discrepancy == -1`; PRD §3.5 defines it as `package_count` minus `packages_reported`, so `test_11` asserts `+1`.
3. `replaced_seal_event_restores_integrity_without_lifting_the_system_hold` asserts `movement.seal_number == "SEAL-101"`; the PRD only writes `seal_number` at departure, so `test_14` translates the instance but omits that one non-derivable sub-assertion.
4. `hold_release_and_amendment_decision_cannot_be_repeated` has the *placing* officer retry the release, which would return `ERR_SEGREGATION_OF_DUTIES` (band 4) and never the asserted `ERR_HOLD_INVALID_STATE` (band 9); `test_15` retries as the other officer so the asserted code is genuinely reached. The same recipe's stale-version reuse was replaced with a live version read for the same reason (the hold place/release mutated the movement).

Also worth noting: `filing_without_any_bond_returns_no_eligible_bond` filters the ledger by `movement_id=${c1}` (a carrier id); `test_15` asserts an unfiltered ledger `total_count == 0` instead. One helper was added this session — `headers_without_identity()` in `test_helpers/test_users.py` — for the wholly anonymous request that rbac instance 1 needs. The task directory has no implementation (`workspace/` holds only `PRD.md` and `INSTRUCTION.md`), so the suite was verified statically rather than executed.

## Step 6: Generate implementation — 2026-09-01T14:32:08.000Z

The implementation is complete and validated.

## Files created

`/home/ubuntu/github/CodingPRD/tasks/task_2254_bond_movement_bonded_carrier_operations/workspace/implementation/`

- `start.sh` (executable) — foreground launcher; `PORT` env var (default 10000), binds `0.0.0.0`, installs Flask only if not importable, then `exec python3 app.py`
- `requirements.txt` — `flask>=2.0`
- `app.py` — `create_app()`, 10 blueprints, error handlers for `ApiError`/404/405/400/unexpected
- `db.py` — in-memory `Store` (12 dicts), logical clock defaulting to `2026-08-01T00:00:00Z`, ISO helpers, `new_record`/`touch`/`order_key`
- `errors.py` — all 55 error IDs → HTTP status map, `ApiError`
- `response.py` — meta/envelope builder, pagination reader (`ERR_INVALID_PAGINATION`)
- `validate.py` — band-5 shape helpers (all raise `ERR_INVALID_REQUEST`)
- `middleware.py` — `X-User-ID` / `X-User-Role` (falls back to `X-Role`), 401/403 gates
- `services/calc.py` — constants plus the 10 normative calculations
- `services/domain.py` — ledger replay, bond/port/sanction recomputation, cascades, 12 serializers
- `routes/` — `registry.py`, `movements.py`, `seals.py`, `holds.py`, `amendments.py`, `reports.py`, `claims.py`, `petitions.py`, `sweeps.py`, `clock.py`

3,055 lines of Python; **41 endpoints** (40 under `/in-bond` + `POST /_clock/set_current_utc`), verified one-for-one against the PRD §4 endpoint table. Storage is pure in-memory dicts; boot seeds nothing.

## Notable design decisions

- **Strict 14-band validation order** everywhere (auth → role → identity binding → SoD → shape/pagination → existence → uniqueness → OCC → own state → other records' state → cargo/seal safety → temporal → business → fiscal). Band 3/4 checks peek at the body without raising so a non-existent target still yields a 404 from band 6.
- **Derived-never-stored money**: `obligated_amount`/`available_amount` come from replaying the append-only ledger; `balance_after` is written per entry; `ACTIVE ↔ SATURATED` is re-derived on every append. Decimal throughout, serialized as floats.
- **Deliberately opposite window conventions** kept separate: closed intervals for STB bond collisions, half-open for exam-bay capacity.
- **Version discipline**: `version` bumps only when a value actually changes, one `touch` per record per request; carrier `overdue_movement_count`/`open_claim_count` are computed live (no bump), port `open_hold_count` is stored (bumps).
- Determinism: an insertion counter `_seq` is the `created_at` tiebreak in every ordering, including ledger replay and bond-selector ranking.

## Spec conflicts resolved

- Auth header: `X-User-Role` read first, `X-Role` accepted as fallback (PRD/SCAFFOLD disagree).
- `requested_days` shape validates only `>= 1`; the `> 30` case is `ERR_EXTENSION_LIMIT_EXCEEDED` (422) per SCAFFOLD's band-5 description, not a 400.
- `package_discrepancy` is the integer `package_count - packages_reported`.
- Report band 9 and the diversion check are skipped when the type is not permitted for the `in_bond_type`, so `ERR_REPORT_TYPE_NOT_ALLOWED` stays reachable; `FILED` falls through band 9 so `ERR_SEAL_NOT_APPLIED` can fire.
- Seal-event `port_code` must match a registered port, but `ERR_PORT_NOT_FOUND` is not in that endpoint's error list → `ERR_INVALID_REQUEST`, checked after movement existence.
- Unknown list-filter values return an empty page (list endpoints declare only `ERR_INVALID_PAGINATION`).
- STB collision surfaces as `ERR_NO_ELIGIBLE_BOND` on auto-selection and `ERR_STB_WINDOW_CONFLICT` when `bond_id` is explicit; `ERR_TRANSIT_DEADLINE_PASSED` applies to `EXTENSION` only.

## Verification

Five end-to-end smoke runs against fresh `start.sh` processes (all servers since stopped; only other sessions' processes remain). Every SCAFFOLD worked witness reproduced: obligation 41.75; 35-day transit → `2026-09-05`; overdue measure 7; LATE_ARRIVAL 1234.60 (cargo cap binds); petition round 1 pct 0.50 / net 617.30 / fee 100.00 / offer 717.30; PARTIAL_GRANT 975.95; ledger `OBLIGATE 41.75 → INCREASE_LD 1276.35 → MITIGATE 1017.70 → RELEASE_LD 41.75` with claim entries netting exactly 0.00. Also confirmed (Step 6): throttle 35→17 at 6.0 points, auto-SUSPEND at 10.0 with `FILED` cascade and un-suspend on claim cancellation (cancelled movements not reinstated), diversion anchor rebase vs extension anchor retention, extension cumulative cap at exactly 30, general-order sweep pass honouring the destination port's `go_warehouse_available`, exam capacity refusal with touching windows accepted, hold-release SoD, TE arrival→export→proof→CLOSED, IE same-port routing, petition supplement round 2 (cap 0.75) and `ERR_PETITION_ROUND_LIMIT`. `pyflakes` is clean and every module byte-compiles.

## Step 7: Run tests and iterate — 2026-09-01T14:44:29.000Z

Clean 8-round sweep achieved.

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each).

**Sweep 1:** 76/104 passed in all 8 rounds — identical failure set every round (28 tests, zero flakiness).

**Root cause (single, shared by all 28 failures):** every failure was an exact-string comparison of an ISO 8601 instant. Tests expected `"2026-09-05T00:00:00Z"`; the implementation renders derived instants as `"2026-09-05T00:00:00.000Z"`. Affected fields: `filed_at`, `deadline_anchor_utc`, `transit_deadline_utc`, `resulting_deadline_utc`, `go_deadline_utc`, `arrival_reported_at`, `export_reported_at`, `reported_at`, `run_at`, `scheduled_start`, `scheduled_end`.

Diagnostic outcome — STEP 1a passes (PRD pins each instant's *value* verbatim, e.g. "`transit_deadline_utc` is then `deadline_anchor_utc` advanced by `transit_days_allowed` whole days of 86,400 seconds each"), but STEP 1b splits on the *rendering*: PRD §2.4 mandates three fractional digits only for `created_at`, and §2.2 only for `api_request_timestamp`; it is silent on the fractional-digit rendering of every other derived instant. So a PRD-faithful implementer may render `filed_at` either way, and uniform `.000Z` is the most natural reading of §2.4's discipline. Per STEP 1c/STEP 2 this is a test-layer bug, fixed by keeping the covered assertion (the instant) and dropping the uncovered one (the digit count) — not by changing the implementation's rendering.

**Tests deleted:** none. No test asserted a scaffold-only or PRD-silent rule at the level of its domain claim.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_2254_bond_movement_bonded_carrier_operations/test_helpers/assertions.py` — `assert_field()` (and therefore `assert_fields`, `assert_deadline`, `assert_ledger_entry`, `assert_petition_offer`, which all delegate to it) now compares ISO 8601 UTC instants as parsed instants rather than byte strings, via a new `_as_instant()` / `_INSTANT_RE` pair. Non-instant values keep strict `==` equality, so no other assertion loses strength; type/enum/None/number/id checks are untouched.

**Fixes applied to `implementation/`:** none — no implementation defect surfaced across 16 rounds.

**Sweep 2 (verification):** 104/104 in all 8 parallel rounds, 0 unique failures across the union.

Orchestrator verification: `results.{1..8}.json` all report `passed == total == 104`.

## Step 8: Finalize PRD — 2026-09-01T14:46:58.000Z

`PRD_FINALIZED.md` written. Exactly one edit was needed — the Step 7 diff had a single root cause (instant rendering) and no implementation fixes or test deletions.

## Line counts
- `PRD.md`: 425 lines
- `PRD_FINALIZED.md`: 425 lines (0.0% line delta; the change is inline within §2.4, line 97)

## Changes
- **§2.4 (Record Identity, Audit Fields, and the Logical Clock)** — *insert* — added two sentences pinning that every instant-valued response field is rendered as an ISO 8601 UTC instant with exactly three fractional digits and a trailing `Z` (`2026-09-05T00:00:00.000Z`), that the rendering is uniform across derived instants, computed deadlines, `created_at`/`updated_at`, and caller-supplied instants echoed back (`effective_date`, `expiry_date`, `scheduled_start`, `scheduled_end`, normalised to UTC first), and that an unset instant is null — `implementation/db.py:46-55` (`iso()`), consumed at `implementation/services/domain.py:233,235,266-267,305-314,332,345,358-362,382-384,399,417,447` and `implementation/routes/clock.py:21`.

## Pre-edit search log
- **(a) Subject:** the wire rendering of every ISO 8601 instant the API emits (the Step 7 site was `filed_at`/`transit_deadline_utc`/`run_at`/etc., but the subject is the shared renderer).
- **(b) Paths enumerated:** grepped every `iso(` callsite in `implementation/` — the single renderer `db.iso()` (fixed `%03d` millisecond format, `astimezone(utc)`); `services/domain.py::_common` (`created_at`, `updated_at`, incl. the `full=False` witness serialisers for ledger entries, seal events, sweeps); all ten `*_json` serialisers (`bond_json` `effective_date`/`expiry_date`; `movement_json` `deadline_anchor_utc`, `transit_deadline_utc`, `filed_at`, `arrival_reported_at`, `export_reported_at`, `go_deadline_utc`; `ledger_json` `recorded_at`; `seal_event_json` `occurred_at`; `hold_json` `scheduled_start`/`scheduled_end`/`released_at`; `amendment_json` `decided_at`/`resulting_deadline_utc`; `report_json` `reported_at`; `claim_json` `issued_at`; `sweep_json` `run_at`); `response.py::_meta` (`api_request_timestamp`); `routes/clock.py` (`current_utc` echo). Also read the ingest side — `validate.py::req_dt`/`opt_dt` → `db.parse_iso` — plus the two places client instants are stored as `datetime` (`routes/registry.py:97-115` bond dates, `routes/holds.py:74-76` exam window) to confirm echoed values are re-rendered, not passed through as the caller's literal string. No instant reaches a response body by any route other than `iso()`.
- **(c) Wording adjustment:** the first draft claimed the rule only for "derived instants", which would have mis-described the client-supplied `effective_date`/`expiry_date`/`scheduled_start`/`scheduled_end` echoes and `api_request_timestamp` (wall-clock, not logical-clock). Widened to "every instant-valued field a response body carries", explicitly folding in `created_at`/`updated_at` and the echoed-input case with UTC normalisation, and left the unset case as `null` so the many nullable instant fields elsewhere in the PRD are not contradicted.

## Step 9: Complete PRD — 2026-09-01T14:57:45.000Z

46 lines revised, no lines added or removed.

## Source vs output
- `workspace/PRD_FINALIZED.md`: 425 lines, 88,077 chars
- `workspace/PRD_COMPLETED.md`: 425 lines, 98,665 chars (**+10,588 chars**, 46 lines revised in place, zero lines added/removed, zero new sections)

## Counts
- **ambiguity-pins: 38**
- **mismatch-revisions: 8**

## Changes

**Mismatches (PRD described something impl does not do)**
- §2.6 Bond Obligation Ledger — revise — mismatch — `amount` "never exactly zero" now carves out the `MITIGATE` entry written as exactly 0.00 when relief equals `assessed_amount` — `services/calc.py:189` + `routes/petitions.py:202`
- §2.8 Cascades/Version Semantics — revise — mismatch — a recomputation that moves no value is not a mutation: bond replay, port `open_hold_count`, carrier `sanction_points`, and no-op seal events leave `updated_at`/`version` alone — `services/domain.py:98,130,172`; `routes/seals.py:116`
- §3.1 Participants — revise — mismatch — `irs_number` pattern is documentary only; any non-empty string accepted, uniqueness by exact string — `routes/registry.py:29`
- §3.3 Seal Chain — revise — mismatch — `APPLIED` is *not* system-only: a caller may record it and it behaves as `REPLACED` (writes `seal_number`, sets `seal_intact` true) — `routes/seals.py:60-66`
- §3.3 Seal Chain — revise — mismatch — integrity is restored by `REPLACED` **or** a directly recorded `APPLIED` — `routes/seals.py:67-73`
- §3.3 Seal Chain — revise — mismatch — the `BROKEN_UNAUTHORIZED` *event*, not the auto-hold, is the `SEAL_VIOLATION` witness — `routes/claims.py:32-34`
- §3.4 Amendments — revise — mismatch — `requested_days` has no 30 ceiling in the shape band; >30 falls to `ERR_EXTENSION_LIMIT_EXCEEDED` — `routes/amendments.py:54,91`
- §3.5 Reports — revise — mismatch — band-9 state checks are skipped when the `report_type` can never be admitted, so `ERR_REPORT_TYPE_NOT_ALLOWED` beats `ERR_MOVEMENT_INVALID_STATE` (seal/GO checks still precede) — `routes/reports.py:57-88`

**Ambiguity pins (PRD silent)**
- §2.1 RBAC — insert — `X-Role` honoured as fallback for `X-User-Role` — `middleware.py:14-16`
- §2.2 Response Structure — insert — `api_request_timestamp` is wall-clock, not the logical clock — `response.py:20`
- §2.3 Pagination — insert — non-integer `limit`/`offset` → `ERR_INVALID_PAGINATION`; empty string = omitted — `response.py:51-71`
- §2.3 Pagination — insert — insertion order is the universal tiebreak, running with the primary sort direction — `db.py:100`; `routes/sweeps.py:82`
- §2.4 Clock — insert — clock set returns 200 with `data` = `{current_utc}` only — `routes/clock.py:21`
- §2.5 Money — insert — decimals must be supplied as JSON numbers, not strings — `validate.py:126-127`
- §2.9 Stale-Version — insert — version fields are non-negative integers; malformed → band-5 `ERR_INVALID_REQUEST` before the 412 — `routes/amendments.py:41`; `routes/petitions.py:74`
- §2.10 band 3 — insert — the pre-shape body-borne identity check only fires for a present, string, resolvable reference; otherwise it is re-tested after existence — `routes/movements.py:54-56`; `routes/reports.py:34-38`
- §2.10 band 5 — insert — absent/whitespace body = empty object; non-object body → `ERR_INVALID_REQUEST`; explicit `null` = omitted but `""` invalid — `validate.py:28-37,56-64`
- §2.11 Nested Reads — insert — filters are case-sensitive equality, conjunctive, empty/unknown params ignored, non-matching filter → empty page — `routes/movements.py:195-200`
- §3.1 Participants — insert — bond `expiry_date` must be strictly after `effective_date` (`ERR_INVALID_REQUEST`, band 5, ahead of `ERR_CARRIER_NOT_FOUND`) — `routes/registry.py:100-104`
- §3.1 Participants — insert — surety patch: both fields optional, neither-supplied is a no-op with no version bump; `limit_amount` strictly positive — `routes/registry.py:153-181`
- §3.1 Participants — insert — non-four-digit `port_code` → `ERR_INVALID_REQUEST` ahead of the duplicate test; `exam_capacity_slots` mandatory — `routes/registry.py:192-197`
- §3.2 Filing — insert — existence order: carrier → bond → origin → destination → predecessor — `routes/movements.py:73-91`
- §3.2 Filing — insert — cancellation `reason_code` is mandatory — `routes/movements.py:264`
- §3.3 Departure — insert — non-`BONDED` custody or an `OPEN` hold at departure → `ERR_MOVEMENT_INVALID_STATE`, not `ERR_HOLD_OPEN` — `routes/movements.py:223`
- §3.3 Seal Chain — insert — `port_code` must be four digits and resolve, both `ERR_INVALID_REQUEST` (not `ERR_PORT_NOT_FOUND`), after movement resolution — `routes/seals.py:36-44`
- §3.3 Seal Chain — insert — auto-hold's port, `reason_code` `SEAL_DISCREPANCY`, null window/findings, `discrepancy_pieces` 0, custody moves only from `BONDED` — `routes/seals.py:92-114`
- §3.3 Seal Chain — insert — `ERR_SEAL_NOT_APPLIED` keys on `seal_number` being null rather than on departure — `routes/seals.py:56`
- §3.4 Amendments — insert — `decision_reason_code` mandatory; diversion port + route shape re-checked at approval — `routes/amendments.py:127,141-147`
- §3.4 Amendments — insert — approval re-runs the whole allowance formula, including the sanction throttle at current points — `services/domain.py:208-226`
- §3.5 Reports — insert — `packages_reported` mandatory; proof/conveyance refs accepted and echoed on an `ARRIVAL` report — `routes/reports.py:44-46,97-98`
- §3.5 Reports — insert — the further `ERR_MOVEMENT_INVALID_STATE` cases (2nd arrival after export, export when already `EXPORTED`, `TE` export before arrival) — `routes/reports.py:61-70`
- §3.5 Arrival — insert — arrival is barred only from `ARRIVED`/`EXPORTED`/`CLOSED`/`CANCELLED`, so `FILED` is admissible — `routes/reports.py:64`
- §3.5 Exportation — insert — perfecting ignores `transit_status`; omitted `export_conveyance_ref` preserves the stored value — `routes/reports.py:153-164`
- §3.5 Cargo Release — insert — `reason_code` accepted but never persisted; already-`RELEASED` custody → `ERR_MOVEMENT_INVALID_STATE`; seal-integrity precedes `ERR_HOLD_OPEN` — `routes/movements.py:287-302`
- §3.6 Holds — insert — `reason_code` mandatory; movement resolved before port — `routes/holds.py:26-35`
- §3.6 Holds — insert — `ERR_HOLD_TYPE_NOT_ALLOWED` follows the state check and ignores window/capacity rules entirely — `routes/holds.py:44-67`
- §3.6 Hold Release — insert — `findings_code` mandatory; SOD tested before shape and existence — `routes/holds.py:123-137`
- §3.6 Sweep — insert — `note`, when present, must be non-empty — `routes/sweeps.py:17`
- §3.6 Sweep — insert — pass four walks carriers in `created_at` order and can fire the suspension cascade, which no tally reflects — `routes/sweeps.py:60-62`
- §3.7 Claims — insert — issuance `reason_code` validated then discarded; movement state never examined — `routes/claims.py:51-63`
- §3.7 Claims — insert — `ERR_DUPLICATE_CLAIM` is tested before the witness test — `routes/claims.py:57-63`
- §3.7 Claims — insert — `sanction_points_applied` is the undecayed type weight at one decimal (2.0/3.0/4.0/4.0/6.0) — `routes/claims.py:83`
- §3.7 Petitions — insert — missing/non-array `mitigation_factors` → `ERR_INVALID_REQUEST`; content rules (incl. >5 codes, unknown code) judged after stale-version and claim-status — `routes/petitions.py:19-27,83-87`
- §3.7 Petitions — insert — a petition carries no `decided_at` field — `services/domain.py:425-442`
- §3.7 Petitions — insert — `prior_violation_count` window is closed at both ends — `routes/petitions.py:35-43`
- §3.7 Petitions — insert — decision `decision_reason_code` mandatory; SOD before shape/existence — `routes/petitions.py:157-164`
- §3.7 Supplement — insert — carrier binding tested ahead of shape validation — `routes/petitions.py:124-129`
- §3.7 Disposition — insert — body `action` narrows the authorised role (`ERR_UNAUTHORIZED`) ahead of binding/SOD/shape; `paid_amount` mandatory on `PAY`; `action` absent/unknown → `ERR_INVALID_REQUEST` — `routes/claims.py:122-141`
- §3.7 Disposition — insert — cancel `reason_code` optional, `cancellation_reason` null when omitted — `routes/claims.py:139,170`
- §3.7 Sanction Posture — insert — auto-reinstatement also fires when decay alone drops the score at a sweep — `services/domain.py:167-170`
- §3.7 Petition History — insert — `round` ascending with `created_at` ascending as tiebreak — `routes/petitions.py:215`
