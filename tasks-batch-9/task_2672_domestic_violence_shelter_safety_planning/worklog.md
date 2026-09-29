## Step 1: Create task directory — 2026-09-04T04:40:00.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2672_domestic_violence_shelter_safety_planning and its workspace/ subdirectory. Index 2672 was pre-assigned by the orchestrating command; no scan of ./tasks/ was performed.

## Step 2: Generate scaffold — 2026-09-04T06:27:00.000Z

NOTE (orchestrator): the Step 2 subagent finished writing all three artifacts but was terminated by an upstream API error before it could return its summary message, so no verbatim subagent summary exists for this step. The orchestrator verified the artifacts directly instead; the summary below is the orchestrator's own verification record, not the subagent's report.

Verification performed:
- All three files exist and are non-empty: SCAFFOLD.yaml (3273 lines / 165744 B), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1925 lines / 127123 B), SCAFFOLD_CORNER_DESIGN.yaml (2247 lines / 139926 B).
- All three parse cleanly under `yaml.safe_load`.
- Key separation is correct: SCAFFOLD.yaml top-level keys are [scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles] — it contains NEITHER `scaffold_difficulty_design` NOR `scaffold_corner_design`. SCAFFOLD_DIFFICULTY_DESIGN.yaml has the single top-level key `scaffold_difficulty_design`; SCAFFOLD_CORNER_DESIGN.yaml has the single top-level key `scaffold_corner_design`.

Scaffold content shape:
- domain_name: domestic-violence-shelter-safety-planning; api_prefix: "" (endpoints mounted at root, e.g. /staff-members, /clients).
- complexity_profile: difficulty_level=expert_plus, primary_archetype=compliance_audit, secondary_archetype=quota_allocation, complexity_layers=[cascading_side_effects, optimistic_concurrency, dual_variant_calculation, derived_field_reconciliation, rate_threshold_triggers], entity_topology=flat, state_machine_shape=branching, relationship_patterns=[one_to_many, cross_aggregate, self_referential, polymorphic], role_model=segregation_of_duties, consistency_model=immediate. The "harder than expert level" difficulty instruction was honoured as expert_plus.
- 15 entities: StaffMember, WellnessCheck, Client, HotlineCall, RiskAssessment, SafetyPlan, PlanComponent, Shelter, ShelterUnit, ScreeningRequest, ShelterAdmission, ProtectiveOrderCase, LandlordPartner, HousingReferral, DisclosureEvent.
- 11 state machines, 3 concurrency rules, 8 calculations, 33 validations, 57 endpoints, 47 errors, 6 roles (HotlineAdvocate, ShelterManager, LegalAdvocate, HousingSpecialist, PrivacyOfficer, AgencyAdmin).
- Design indices: DIFFICULTY has 9 rules x 2 instances = 18 instances (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant). CORNER has 50 instances across 4 sections (entities 12, state_machines 16, calculations 13, validations 9). Combined test-source budget: 68 instances.

## Step 3: Copy shared files — 2026-09-04T06:28:00.000Z

Copied ./INSTRUCTION.md to tasks/task_2672_domestic_violence_shelter_safety_planning/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-04T06:47:00.000Z

PRD complete and verified.

**Artifact:** `/home/ubuntu/github/CodingPRD/tasks/task_2672_domestic_violence_shelter_safety_planning/workspace/PRD.md` — 530 lines, written in 13 chunked `cat >>` appends (no single giant Write), ending cleanly at the last row of the §5 error table with no audit footer.

**Structure:** §1 Introduction · §2 with 11 global subsections (2.1 RBAC, 2.2 verbatim response structure, 2.3 pagination/filtering, 2.4 logical clock, 2.5 common properties/version semantics, 2.6 OCC, 2.7 rejection precedence, 2.8 nested path resolution, 2.9 numeric precision, 2.10 immediate reconciliation, 2.11 confidentiality posture) · §3 with 9 workflow subsections · §4 endpoint table (4 columns) · §5 error table (2 columns).

**Hard Contract results (machine-checked against SCAFFOLD.yaml with a YAML-parsing script):**

- **Contract 1 — Field-Name Coverage: PASS.** All 142 identifiers (every `entities[].fields[].name` plus every `request_body`/`input`/`query_params`/`path_params` key across 57 endpoints) appear verbatim in backticks. One initial miss, `safety_plan_id`, was fixed by rewriting the §3.2 component-uniqueness sentence to state the (`safety_plan_id`, `component_type`) uniqueness pair. Every enum token drawn from field constraints is also present in backticks (the only unmatched token was the word `AND` from a constraint expression, not a value).
- **Contract 2 — Rule Coverage: PASS.** All 33 validations appear, and §2.7 lists them as a 33-item global order that matches the scaffold's priority order exactly (10 → 94). All 3 concurrency rules are in §2.6 with their correct `occ_field`, parent entity and 412 error, including the second `expected_shelter_unit_version` site on complete-relocation. All 47 state-machine transitions across the 11 machines are described, including the easily-dropped ones (`ShelterUnit OCCUPIED → HOLD` on an exit from a unit that still holds a reservation, `AVAILABLE → OCCUPIED` on relocation of a checked-in household, `ScreeningRequest ADMITTED → APPROVED` on cancel, `WAITLISTED → EXPIRED` on clock advance, `PlanComponent BLOCKED → IMPLEMENTED`). All 8 calculations are specified with mandatory evaluation order and worked illustrations where the scaffold supplies precision notes (notably the read-tier-before-commitment ordering in `landlord_engagement_incentive`, 40000/BASE then 59000/SILVER, and the round-then-sum ordering in `safety_plan_coverage_score`, 1.76 not 1.75).
- **Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 start with `/`, are a bare HTTP method, or combine method+path; there is also no unticked method+path text in §3. All URL paths live in §2.6 and §4 only.

**Other checks:** §2.2 is byte-identical to `section-2.2-response-structure.md` (appended via `cat`, verified by substring match). All 57 endpoints present in §4 as `| METHOD | \`path\` |` rows with scaffold role lists; all 47 errors present in §5 with HTTP statuses matching the scaffold exactly. No fuzzy language ("approximately", "roughly", "etc.", "as appropriate") and no pseudocode operators (`==`, `>=`, `+=`, `min(`, `round(`, ` IN `) outside backticked identifiers.

**Two judgement calls worth flagging to the implementer-side reviewer:** the scaffold specifies two preconditions without a dedicated error ID — check-in before `entry_date`, and record-outcome before `hearing_end_utc`. Both are written as `ERR_INVALID_STATE_TRANSITION`, consistent with that validation's stated scope. Also, the `HousingReferral → REJECTED` transitions are documented as firing both from the location-compromise cascade and from archiving a client's `ACTIVE` safety plan (including via `revise`), matching the union of the transition trigger and the `revise` endpoint's own declared side effects.

The two design YAMLs (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced, and no sibling task directory was read.

**Orchestrator truncation audit (guarding the known doc-generator failure mode):** PRD.md is 530 lines / 106733 bytes and its tail is the final `| \`ERR_LANDLORD_NO_UNITS_AVAILABLE\` | 409 |` table row — a real section boundary, not a mid-sentence cut. Independently re-verified against SCAFFOLD.yaml: 47/47 error ids present (0 missing) with exactly 47 rows in §5, and 57/57 endpoint paths present (0 missing) with exactly 57 rows in §4. All 26 expected headings (§1, §2 + 11 subsections, §3 + 9 subsections, §4, §5) are present in order. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T07:44:00.000Z

Suite complete.

## What was delivered

`test_helpers/` (9 files, 2302 lines) and `test_suite/` (conftest + 13 test modules, 4341 lines) — both at the **task root**, `/home/ubuntu/github/CodingPRD/tasks/task_2672_domestic_violence_shelter_safety_planning/`. `find` confirms neither directory (nor any `test_*.py`) exists anywhere under `workspace/`.

**74 tests, all collecting cleanly** (`pytest --collect-only -q` → "74 tests collected in 0.71s").

Line counts: helpers — `__init__` 38, `api_client` 262, `api_errors` 110, `assertions` 316, `constants` 130, `factories` 319, `fixtures` 763, `test_users` 74, `types` 290. Suite — `conftest` 41, test_01 202, test_02 194, test_03 191, test_04 388, test_05 238, test_06 187, test_07 320, test_08 241, test_09 262, test_10 565, test_11 481, test_12 411, test_13 620.

## Verification passes (all green)

- **Coverage**: 18/18 queue-A instances have ≥2 tests; 36/36 non-stub queue-B instances have ≥1 test; none of the 14 `excluded_because:` stubs was translated.
- **Design tags (C4)**: exactly one `Design:` line per test, all 74 resolving to a real non-stub instance name; no test mentions "scaffold".
- **PRD citations (C1–C3)**: every `PRD: "…"` quote in all 13 modules is a whitespace-normalised verbatim substring of `workspace/PRD.md` (0 misses), and a sentence-boundary sweep flagged only three false positives (two markdown bullet items, one line-initial sentence).
- **Static**: every module `ast.parse`s, no unused imports, no undefined names, and every symbol imported from `test_helpers` exists in the barrel.

## Judgement calls worth relaying

- **test_03 refile chain**: the design's `setup_api_calls` recorded `DENIED` outcomes while the clock was still before `hearing_end_utc`, which PRD line 352 refuses. I rebuilt the chain PRD-consistently (clock advance before each outcome) and moved the terminal assertion to `2026-08-22T12:00:00`.
- **test_12 HMIS projection**: the design asserts the client's `version` increments after a `RELEASE` decision, but PRD line 410 says only the deny path moves the client's version ("on every other path only the event's `version` moves"). I asserted the PRD behaviour — client version unchanged — and kept the rest of the instance.

## Step 6: Generate implementation — 2026-09-04T07:20:00.000Z

The implementation is complete.

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_2672_domestic_violence_shelter_safety_planning/workspace/implementation/` — Python + Flask, in-memory only, 25 files, 3272 lines total.

Per-file line counts:

| file | lines | file | lines |
|---|---|---|---|
| `start.sh` (+x) | 10 | `routes/staff.py` | 83 |
| `requirements.txt` | 1 | `routes/clients.py` | 73 |
| `app.py` | 84 | `routes/hotline.py` | 204 |
| `db.py` | 136 | `routes/plans.py` | 201 |
| `errors.py` | 79 | `routes/shelters.py` | 98 |
| `response.py` | 62 | `routes/screening.py` | 136 |
| `middleware.py` | 49 | `routes/admissions.py` | 288 |
| `validation.py` | 288 | `routes/protective.py` | 151 |
| `services/calc.py` | 339 | `routes/housing.py` | 202 |
| `services/derive.py` | 295 | `routes/disclosure.py` | 151 |
| `services/cascade.py` | 156 | `routes/clock.py` | 59 |
| `routes/common.py` | 127 | `routes/__init__.py`, `services/__init__.py` | 0 |

All files written via chunked `cat >>`/heredoc appends, each `wc -l`'d and `python3 -m py_compile`'d; a final compile of every module passes.

## Coverage

**57 endpoints registered** (verified by counting `url_map` method/rule pairs), 15 entities, 11 state machines, 3 OCC guards (`expected_shelter_unit_version` on admission-create and complete-relocation, `expected_client_version` on safety-plan create, `expected_landlord_partner_version` on referral match), 8 calculations (all `Decimal` ROUND_HALF_UP, money as whole-cent ints), 47 error ids with their PRD HTTP statuses, 6 roles from `X-User-ID`/`X-User-Role`, and the §2.7 33-step rejection precedence (SoD and plan-authorship resolve the governing path row before the 403, then shape; everything else validates shape before path 404s).

## Verification

- **Storage**: pure `dict` store in `db.py`, empty on every boot; no `sqlite`, no `open(`, no `json.dump`, no `/tmp` anywhere in the tree; nothing seeded or hardcoded.
- **Functional smoke** (in-process test client, ~55 assertions): danger score 92.0 x 1.25 = 100.0 IMMINENT; posture NORMAL→HEIGHTENED→SEALED→HEIGHTENED across the compromise/relocation cascade; the PRD's worked incentive example reproduced exactly (first match BASE 40000 then score 25.0, second `RAPID_REHOUSING` match SILVER 44000+15000 = **59000**); five-link compromise cascade (plan→UNDER_REVISION, referral→REJECTED/`SAFETY_PLAN_SUSPENDED`, landlord ledger reversed to 59000); `COURT_SUBPOENA` projection returning `["legal_name","entry_date"]` released / `["shelter_street_address"]` suppressed in canonical order with PARTIALLY_RELEASED; `MANDATED_REPORT` deadline `created_at`+24h and `late_filed` strictly-after; ±60-minute travel-buffer double-booking (12:00 conflicts, 13:01 clears); refile loop clearing the hearing window; waitlist promotion on exit plus clock-driven expiry (`requested_entry_date`+14d at 00:00:00Z, `expired_screening_request_count` 1, positions renumbered); OCC 412s, SoD 403s, 401/403/404/409/422 envelopes.
- **Live server smoke**: `PORT=18672 bash start.sh` booted fresh, returned the PRD envelope (`meta.api_request_id` `req_…`, `response_type`, `data`), created a staff member at `version` 1 with `created_at` `2026-08-01T00:00:00.000Z`, advanced the clock, and returned `ERR_UNAUTHENTICATED` without headers. Killed by its single specific PID (2507872); port confirmed free. **No broad kill command was ever run.**

Two spec ambiguities resolved: `MANDATED_REPORT` *can* be denied (PRD §3.9 prose describes the deny path and marks it late; the scaffold's "may never be denied" aside has no error id in the catalogue), and "exactly one ACTIVE safety plan" is enforced as `count != 1 → ERR_NO_ACTIVE_SAFETY_PLAN`.

**Orchestrator verification of Steps 5+6:** launched in a single assistant message so the impl generator started before `test_suite/` existed (physical isolation confirmed by its own report that it never read tests). Independently re-checked: no `test_helpers/`, `test_suite/`, or `test_*.py` anywhere under `workspace/`; 23 .py files across the two test dirs; 74 `def test_` functions; `workspace/implementation/start.sh` present and executable; only one `worklog.md` in the tree (no cwd-drift strays).

## Step 7: Run tests and iterate — 2026-09-04T07:56:00.000Z

Clean 8-round sweep confirmed on disk.

## Summary

**Iterations run:** 2 (each an 8-round parallel `setsid` sweep, 74 tests × 8 rounds). Iteration 1: 68/74 in all 8 rounds — 6 deterministic failures, zero flakiness. Iteration 2: **74/74 in all 8 rounds.**

**Tests deleted:** none. All 6 failures traced to test-layer defects (STEP 2), not to PRD silence and not to the implementation.

**Fixes applied to `test_helpers/`:**
- `test_helpers/assertions.py` — added `assert_same_instant(actual, expected)` (plus a `datetime` import): compares two ISO 8601 UTC strings as instants rather than byte for byte. PRD §2.4 puts client-supplied timestamps (`checked_on_utc`, `hearing_start_utc`, `hearing_end_utc`) in a separate category from server-written ones and fixes only that they "are ISO 8601 UTC instants … validated against the logical clock"; §2.5 mandates three fractional digits only for `created_at`/`updated_at`. The response serialisation of a client-supplied instant is therefore not uniquely derivable (verbatim echo and canonical re-rendering are both PRD-faithful readings), so the covered assertion — the recorded window is the instant that was filed — is kept while the format-specific literal comparison is dropped (STEP 1c split).

**Fixes applied to `test_suite/`:**
- `test_02_combinatorial_formulas.py` (2 assertions, both match tests) — read the landlord partner's accrued incentive under the non-existent key `accrued_incentive_cents`; PRD names the field `incentive_accrued_cents` (§3.8). Straight field-name typo producing `KeyError`.
- `test_04_transitive_cascades.py::test_compromise_rejects_the_matched_referral_and_reverses_the_landlord_ledger` — asserted `withdraw_count == 0` on the **landlord partner** payload. PRD puts `withdraw_count` on the `HousingReferral` ("starts at `SUBMITTED` with … `withdraw_count` 0"), and the cited rule ("the cascade rejection … does **not** touch `withdraw_count`") is about the referral. Moved the assertion onto the rejected referral, which is where it faithfully expresses the PRD rule.
- `test_08_resource_temporal_overlap.py` (3 sites) and `test_11_state_machine_corners.py` (1 site) — hearing-window echo assertions switched to `assert_same_instant`; the surrounding core assertions (`ERR_ADVOCATE_DOUBLE_BOOKED`, successful second filing, GRANTED keeping its hearing window and advocate, `outcome_recorded_at` with three fractional digits as a **server-written** timestamp) are all unchanged.

**Fixes applied to `implementation/`:** none. No implementation defect was found; nothing was added, weakened, or removed, and no data is seeded at startup.

**Orchestrator verification of Step 7 (per the "verify the sweep artifacts yourself" rule):** all 8 of `workspace/implementation/results.{1..8}.json` exist on disk from the final sweep (each ~22.7 KB, all timestamped 07:55) and every one reports `passed=74, failed=0, errors=0, skipped=0, total=74`. Independently re-checked the test tree: 74 `def test_` functions still present (matching Step 5's 74 — so the zero-deletions claim holds) and zero occurrences of `pytest.mark.skip` / `pytest.mark.xfail` anywhere in `test_suite/` or `test_helpers/`.

**Step 8 gate:** NOT skipped. The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes; this run had 4 `test_suite/` sites and 1 `test_helpers/` addition, so Step 8 runs with those items as its `<step_7_diff>`. Note for Step 8: although `implementation/` was never patched, the `assert_same_instant` relaxation marks a genuine PRD silence — the serialisation format of client-supplied instants (`checked_on_utc`, `hearing_start_utc`, `hearing_end_utc`) in responses — which PRD_FINALIZED.md should pin to whatever the implementation actually emits.

## Step 8: Finalize PRD — 2026-09-04T08:01:00.000Z

`PRD_FINALIZED.md` is written. One edit, one line touched.

## Line counts
- `PRD.md`: 530 lines
- `PRD_FINALIZED.md`: 530 lines
- Delta: 0 lines (0.00%); 1 of 530 lines modified in place (0.19% of lines)

## Changes
- **§2.4 The Logical Clock (line 92)** — insert — pinned the response serialisation of instants: every instant the API emits, server-written or client-supplied, is canonical ISO 8601 UTC with exactly three fractional digits and a trailing `Z`; a client-supplied instant is normalised into that form rather than echoed verbatim, with `2026-08-05T09:00:00+00:00` → `2026-08-05T09:00:00.000Z` as the worked example — `implementation/db.py:60` (`iso()`), `implementation/validation.py:205-207` (`dt_out`), `implementation/routes/staff.py:66`, `implementation/routes/protective.py:104-105`.

No other PRD edits. The remaining `<step_7_diff>` items were verified as pure test-layer defects, not PRD silence:
- `accrued_incentive_cents` KeyError — PRD line 360 already names `incentive_accrued_cents`, and `implementation/routes/housing.py:50` / `implementation/services/derive.py:266,271` use exactly that name. Fixture typo only.
- `withdraw_count` asserted on the landlord partner — PRD line 362 already places `withdraw_count` on the `HousingReferral`, and `implementation/routes/housing.py:88,171` only ever writes it on the referral row; no landlord-partner field of that name exists anywhere in `implementation/`. Fixture bug only.

## Per-edit pre-edit search log

**Edit 1 — §2.4 instant serialisation**
- (a) Subject: how any datetime-valued field is rendered into a JSON response, in particular client-supplied instants (`checked_on_utc`, `hearing_start_utc`, `hearing_end_utc`) but necessarily also every sibling instant field, since a claim about "instants" is global.
- (b) Paths enumerated (read or grepped): `implementation/db.py:60-85` (`iso`, `clock_iso`, `wall_iso` — the sole datetime renderer); `implementation/validation.py:177-211` (`parse_datetime` accepting `Z`, `+00:00`, naive-as-UTC and non-UTC offsets; `dt_out` delegating to `iso`; `date_out` separately handling date-only fields); client-supplied write sites `routes/staff.py:54,66`, `routes/protective.py:70-71,104-105`, `routes/clock.py:23,56`; server-written sites `routes/hotline.py:39,162`, `routes/screening.py:119,127,133`, `routes/protective.py:131`, `routes/disclosure.py:71,78`, `services/cascade.py:27,151`, `routes/common.py:16`, `db.py:120`, `response.py:20`; derived copy site `services/derive.py:226-230` (`last_wellness_check_at` reuses the already-canonical stored string, and the wellness-check list sort at `routes/staff.py:82` relies on that canonicality for lexicographic ordering); read-back parsers `services/derive.py:16-34`. A repo-wide grep for `isoformat|strftime` confirmed the only non-`iso()` formatter is `date_out` for `YYYY-MM-DD` date-only fields, so no path contradicts a universal claim about instants.
- (c) Wording adjustments made: (i) scoped the universal to "every instant this API emits" rather than "every timestamp", so the `YYYY-MM-DD` date-only fields described in the very next sentence of the same paragraph are untouched; (ii) said "normalised into that form when it is stored and read back" instead of naming a specific endpoint's echo, so the statement equally covers the stored-string reuse in `last_wellness_check_at` and the `current_utc` echo of `to_iso8601`; (iii) deliberately did **not** enumerate which input spellings are accepted — the impl accepts `Z`, explicit offsets and naive strings, so any narrower input claim would have been a new mismatch; the sentence only constrains output.

**Orchestrator verification of Step 8:** `diff PRD.md PRD_FINALIZED.md` returns exactly one hunk, `92c92` — a single in-place line revision, no additions, no deletions, no new sections. Both files are 530 lines and PRD_FINALIZED.md still ends at the final §5 error-table row (`ERR_LANDLORD_NO_UNITS_AVAILABLE`), so nothing was truncated by the patch.

## Step 9: Complete PRD — 2026-09-04T09:00:00.000Z

Run as THREE sequential file-partitioned passes over `implementation/` rather than one scan, because a single-pass Step 9 has historically produced a byte-identical PRD_COMPLETED.md (i.e. the scan silently never ran). Pass A created the file from PRD_FINALIZED.md and scanned the cross-cutting machinery; passes B and C edited the same file in place. Final: 530 lines, 125,930 chars, 60 lines revised versus PRD_FINALIZED.md, 41 total edits.

### Pass A — cross-cutting/global (app.py, db.py, errors.py, middleware.py, response.py, validation.py, routes/common.py, routes/clock.py)

16 Edit calls touching 18 distinct lines, all in-paragraph. 107,200 → 116,150 chars (+8,950). 14 ambiguity-pins, 4 mismatch-revisions.

- §2.1 — insert — ambiguity — a present-but-empty header counts as missing; role matched case-sensitively without trimming — `middleware.py:36-39`
- §2.2 (`api_request_id`) — insert — ambiguity — `req_` + exactly 20 upper-case-letter/digit chars, minted fresh per response including errors, never echoed — `response.py:13-14`
- §2.2 (`api_request_timestamp`) — insert — ambiguity — read from the host's real wall clock, not the logical clock — `response.py:20`, `db.py:84-85`
- §2.2 (pagination) — insert — ambiguity — pagination meta on list responses only; `has_more` = `offset + len(data) < total_count` — `response.py:40-51`
- §2.3 ¶1 — insert — ambiguity — `limit`/`offset` strict: out-of-range, non-integer, blank all give `ERR_INVALID_REQUEST` rather than clamping; `offset` past the end returns an empty page with full `total_count` — `validation.py:222-246`
- §2.3 ¶2 — insert — ambiguity — creation-sequence is the total tie-break on `created_at` ordering (load-bearing because the frozen logical clock makes `created_at` collide); `unit_label` compared as a string — `routes/common.py:101-102`, `routes/shelters.py:90-91`
- §2.3 ¶3 — insert — ambiguity — filters are exact string equality; vocabulary-valued filters reject unknown values; id filters need not exist but must not be empty; undeclared query params ignored — `validation.py:249-264`, `routes/common.py:105-120`
- §2.4 ¶1 — insert — ambiguity — `to_iso8601` required; an equal instant is accepted and still runs the pass; new reading installed before the pass; expiry runs before wellness re-derivation — `routes/clock.py:19-53`
- §2.4 ¶1 — insert — **mismatch** — `restaffed_posture_count` counts only posture changes while a staff `version` bumps whenever any derived wellness field changed, so the two need not agree — `routes/clock.py:51-53`, `services/derive.py:234-245`
- §2.4 ¶2 — insert — ambiguity — accepted input spellings for instants (`Z`/`z`, explicit offset converted to UTC, zone-less read as UTC); sub-millisecond digits truncated not rounded — `validation.py:177-192`, `db.py:60-68`
- §2.4 ¶2 — insert — ambiguity — date-only fields parsed strictly, read back zero-padded, time/zone components rejected — `validation.py:157-164,210-211`
- §2.5 ¶1 — insert — ambiguity — `id` is a v4 UUID in canonical lower-case hyphenated form; underscore-prefixed internal keys stripped from every serialisation — `db.py:56-57,124-128`
- §2.5 (`created_at`/`updated_at`) — insert — ambiguity — both are logical-clock readings; `updated_at` equals `created_at` on creation and does not move for a mutation in the same clock reading — `routes/common.py:12-24`, `db.py:120`
- §2.5 (`version`) — revise — **mismatch** — the unit of accounting is the request: one request increments a row's `version` by at most 1 however many cascade links land on it, and a row the request created stays at 1 — `db.py:100-121`
- §2.5 ¶4 — insert — **mismatch** — a re-derivation recomputing every field to its existing value may leave `updated_at`/`version` alone, but §3-declared increments are forced regardless — `services/derive.py:70-77,243-244,274-275`
- §2.6 ¶last — insert — ambiguity — unrecognised body keys ignored everywhere — `validation.py:17-27`
- §2.7 step 5 — insert — ambiguity — explicit `null` == absent; absent/empty/unparseable body read as `{}`; JSON non-object body rejected; `Content-Type` never inspected; empty string never legal for a string field; no type coercion; integer fields reject fractional values; enums case-sensitive — `validation.py:17-136`
- §2.7 ¶last — insert — **mismatch** — steps 3 and 4 are evaluated after the path identifier whose row they inspect resolves, but still before all shape checks and remaining id resolution; `ERR_NOT_PLAN_AUTHOR` precedes the component 404 — `routes/screening.py:86-92`, `routes/disclosure.py:104-108`, `routes/plans.py:127-130`
- §5 intro — insert — ambiguity — `ERR_NOT_FOUND`/404, `ERR_METHOD_NOT_ALLOWED`/405 and `ERR_INTERNAL`/500 sit outside the catalogue, share the envelope, and the first two are decided by routing before authentication; trailing slash tolerated — `app.py:39,53-74`

Pass A verified already-pinned: error-envelope shape; `response_type` values; empty `data` for dataless 2xx; **the entire `errors.py` status map — all 47 ids match §5 exactly**; auth-before-authorisation ordering; the six role spellings; `AgencyAdmin`'s id never satisfying an ownership check; `role_type` never consulted for authority; clock epoch `2026-08-01T00:00:00Z`; monotonicity with equality allowed; canonical instant output; `WellnessCheck`/`RiskAssessment` carrying only `id`+`created_at`; 201-vs-200 (15 `created()` sites = 15 create endpoints); `total_count` over the filtered set; wellness-check list ordering; 14-day waitlist TTL with per-shelter renumbering. (`q_bool`, `q_date`, `paginate`, `opt_str` are dead code — nothing to pin.)

### Pass B — engines + intake routes (services/calc.py, derive.py, cascade.py, routes/staff.py, clients.py, hotline.py, plans.py)

23 edits, 116,150 → 120,668 chars. 14 ambiguity-pins, 9 mismatch-revisions.

- §2.1 — insert — ambiguity — the acting `X-User-ID` is never resolved against the staff collection; an unknown id is still stamped and never yields `ERR_STAFF_MEMBER_NOT_FOUND` — `middleware.py:45-49` with `hotline.py:36`, `plans.py:53`
- §2.6 — revise — ambiguity — expected-version fields must be an integer ≥ 0 — `plans.py:37`, `admissions.py:48/243`, `housing.py:116`
- §2.6 — insert — **mismatch** — the `SAFETY_PLAN_ONLY` disposition branch authors a plan with **no** expected-version field (PRD's "creating a safety plan must carry it" was a false universal) — `hotline.py:187-198`
- §2.9 — revise — **mismatch** — the blanket "per-term first then the total" rule was wrong for the trauma index; now pinned per computation (coverage = per component + total; index = one rounding over the decayed sum; `danger_score` = one rounding after the multiply) — `calc.py:160-169,280-288,98`
- §3.1 — insert — ambiguity — `client_code` uniqueness is an exact character comparison — `clients.py:37-39`
- §3.1 — insert — ambiguity — the `minor_children_count ≤ household_size - 1` ceiling is `ERR_INVALID_REQUEST` — `clients.py:31-32`
- §3.1 — insert — ambiguity — latest-assessment selection breaks a `created_at` tie by creation sequence — `derive.py:50-54,122-131`
- §3.1 — insert — ambiguity — dispose returns the disposed **call**, never the child screening/plan — `hotline.py:204`
- §3.1 — insert — ambiguity — branch-A screening's remaining starting fields (nulls, `promoted_from_waitlist` false, `version` 1) — `hotline.py:170-186`
- §3.2 — insert — ambiguity — `target_completion_date` is never compared to the clock, and adding a component is not gated on plan status (allowed even on `ARCHIVED`) — `plans.py:85-111`
- §3.2 — insert — ambiguity — a new component's own `weight_effective`/`subscore` are computed in the creating request, so the 201 body is not zeros — `plans.py:100-109`, `derive.py:177-197`
- §3.2 — insert — ambiguity — implement returns the updated **component**, not the plan — `plans.py:149`
- §3.2 — revise — **mismatch** — "once the component statuses have settled" implied suspension rewrites components; it does not — `plans.py:168-183`
- §3.4 — revise — **mismatch** — `exposure_hours` is any number in 0–200 (whole numbers accepted, finer precision stored as supplied, never rounded to a tenth) — `staff.py:55`, `validation.py:84-92`
- §3.4 — revise — **mismatch** — a **waitlisting** re-derives no advocate — `screening.py:122-129`, `derive.py:217`
- §3.4 — insert — ambiguity — `waitlist_position` tie-break by creation sequence; renumbering assigns 1..n in that order — `cascade.py:90-105`
- §3.4 — revise — **mismatch** — promotion ranking: `created_at` is not total; internal creation sequence is the final tie-break — `cascade.py:130-134`
- §3.6 — insert — ambiguity — link 3 leaves `REVIEW_REQUIRED`/`BLOCKED` components alone, and is a silent no-op when the client has no `ACTIVE` plan — `cascade.py:63-74`
- §3.6 — revise — ambiguity — link-5 deltas are per rejected `MATCHED` referral and the five partner counters are full recomputations, so one partner losing two matches drops by two — `cascade.py:33-50`, `derive.py:252-275`
- §3.9 — insert — ambiguity — consent change reads body key `hmis_disclosure_consent`, bumps `version` even when unchanged, does not re-derive `confidentiality_posture`, and is ungated by client `status` — `clients.py:65-73`
- §4 (POST /staff-members) — revise — **mismatch** — "starting wellness posture" is not a payload field; it is always `OPEN` — `staff.py:25-41`
- §4 (POST components) — revise — **mismatch** — "to a draft or revising safety plan": no status guard exists — `plans.py:85-89`
- §4 (POST activate) — revise — **mismatch** — "archiving any previously active plan": activation archives nothing (archival happens at plan creation) — `plans.py:152-165`

Pass B verified already-pinned: all lethality weights/stalking cap/bonus/multiplier/rounding-then-cap/band thresholds; `capacity_posture_of` with integer ceil(20%) and `unit_status_of`; base weights, 1.2 uplift at 2dp, status factors, subscore ÷10, per-component-then-total summation, 11.10 maximum; per-night base, projected night count with half-up weekend estimate, settled Fri/Sat calendar walk; engagement score, tier thresholds/multipliers, fee rounding before the 15000 `RAPID_REHOUSING` bonus; `contribution_points` (×0.70 before rounding), decay 1.0/0.6/0.0 bands, 2.5-per-caseload, cap after rounding, posture thresholds; disclosure allowed-sets, canonical key order, DENY as total suppression, `RELEASED` vs `PARTIALLY_RELEASED`; unit/shelter bed-ledger sums with terminal admissions excluded; `settled_revenue_cents` as the EXITED total; client risk mirror and three-value posture severity order; `active_caseload_count` incl. the EXITED exclusion; `last_wellness_check_at`; partner ledger recomputation set; half-open stay-window overlap; supersession set with `archived_at`/`superseded_by_plan_id`; referral rejection reason and fee/tier clearing without touching `withdraw_count`; compromise link order and `WORKPLACE_NOTIFICATION`-only blocking; the six promotion eligibility conditions; expiry renumbering; all four modules' role lists, required/optional fields and defaults (`max_caseload` 8, `debrief_completed` false, `corroborate_with_history` false, `location_confidential` true, consent `DENIED` with `REVOKED` refused), header-stamped ids, state guards and error ids, guard ordering vs §2.7, wellness-check immutability, `revision_count` on return only.

### Pass C — placement/legal/housing/disclosure routes (routes/shelters.py, screening.py, admissions.py, protective.py, housing.py, disclosure.py)

23 edits, 120,668 → 125,930 chars. 16 ambiguity-pins, 7 mismatch-revisions. §4 still 57 rows, §5 still 47 rows.

Three items pass B flagged into pass C's partition, all resolved:
1. **§3.3 disclosed-address guard — pass B was right; the claim was removed.** A grep over the whole implementation shows `confidential_location` is written at `shelters.py:26,33` and `location_confidential` at `clients.py:34,47` and **read nowhere** — not in `admissions.py`, `screening.py`, or anywhere else. The sentence now says the flag is documentary only, gates no placement, and that what actually keeps an address inside the agency is the §3.9 projection (which withholds `shelter_street_address` by `kind` alone, `calc.py:317-324`).
2. **§4 `POST /screening-requests` — mismatch confirmed and fixed.** `screening.py:48` inserts `assigned_advocate_id: None`, verified live. The row now reads "opens at `PENDING` with `assigned_advocate_id` still null, an advocate being named only by the decision endpoint."
3. **§3.9 raise roles — count fixed.** `disclosure.py:22-23` has `RAISE_ROLES = (PrivacyOfficer, HotlineAdvocate, LegalAdvocate, ShelterManager)`. Rewritten as "The three staff roles … in the field — `HotlineAdvocate`, `LegalAdvocate` and `ShelterManager` — may raise one, as may a `PrivacyOfficer`, which makes four roles in all … an `AgencyAdmin` may not log one at all, though an `AgencyAdmin` may read and list them."

- §3.3 — revise — **mismatch** — disclosed-address host guard deleted; both confidentiality flags declared write-only — `shelters.py:26`, `clients.py:34`
- §3.3 — insert — ambiguity — `weekend_surcharge_cents`/`child_supplement_cents` accepted 0..50000, negatives `ERR_INVALID_REQUEST` — `shelters.py:28-29`
- §3.3 — revise — **mismatch** — facility `version` moves only when the roll-up figures move; explicitly not on a check-in — `derive.py:83-97`
- §3.4 — insert — ambiguity — screening-open: all four fields required, FK order `client_id`→`hotline_call_id`→`requested_shelter_id`, un-triaged call is `ERR_INVALID_STATE_TRANSITION`, cross-ref reported first — `screening.py:27-41`
- §3.4 — insert — ambiguity — `DENY`: `denial_reason` 1..2000 chars; no `assigned_advocate_id` read — `screening.py:101`
- §3.4 — insert — ambiguity — `WAITLIST` gated by neither shelter capacity nor `max_caseload` — `screening.py:122-128`
- §3.5 — insert — ambiguity — reserve: five required inputs, `screening_request_id` resolved before `shelter_unit_id`, neither date compared to the clock — `admissions.py:44-51,63`
- §3.5 — insert — ambiguity — `requested_shelter_id` is never compared with the unit's `shelter_id`; `offered_shelter_unit_id` is advisory — `admissions.py:50-81`
- §3.5 — revise — **mismatch** — check-in: entry-date gate precedes the compromise check; `PENDING` stays `PENDING` when the flag is false; facility `version` does not move — `admissions.py:133-146`
- §3.5 — insert — ambiguity — `actual_exit_date` compared only against `entry_date`; a future or post-`planned_exit_date` value is settled over — `admissions.py:161`
- §3.5 — insert — ambiguity — `cancel_reason` 1..2000 chars — `admissions.py:192`
- §3.6 — insert — ambiguity — relocation re-points the admission's `shelter_id`, so a cross-facility move carries pricing and revenue with it — `admissions.py:279`, `derive.py:100-110`
- §3.7 — insert — ambiguity — `filed_court` 1..200 chars, all four filing fields required with no defaults — `protective.py:69-72`
- §3.7 — insert — ambiguity — `outcome` required, drawn from `GRANTED`/`DENIED` — `protective.py:20,121`
- §3.8 — insert — ambiguity — `monthly_rent_cents` integer 0..100000000; partner read from the referral, not the body — `housing.py:115-118`
- §3.8 — insert — ambiguity — `withdraw_reason` 1..2000 chars, validated but never persisted — `housing.py:163`
- §3.8 — revise — **mismatch** — lease sets client `status` to `EXITED` unconditionally, not only from `ACTIVE` — `housing.py:200`
- §3.9 — revise — **mismatch** — raise-role count/list — `disclosure.py:22-23`
- §3.9 — insert — ambiguity — the two ROI dates default null, are not cross-compared or clock-compared at creation; `roi_signed_on` is never inspected by any gate; FK order `client_id` then `requested_by_staff_id` — `disclosure.py:54-57,127-130`
- §3.9 — insert — ambiguity — the initial field set includes `denial_reason` null — `disclosure.py:74`
- §3.9 — insert — ambiguity — decide `denial_reason` 1..2000, ignored on `RELEASE` and left null — `disclosure.py:113-114,141`
- §3.9 — revise — **mismatch** — client `version` moves only on the `HMIS_EXPORT` **denial** path; every other decision path leaves the client untouched — `disclosure.py:148-150`
- §4 — revise — **mismatch** — `POST /screening-requests` description — `screening.py:48`

Pass C ran the app in-process to confirm its two boldest version claims: reserve took shelter v2→v3 and unit v1→v2; **check-in left the shelter at v3** while the unit went v2→v3 (proving the check-in mismatch); and a same-shelter relocation did bump the shelter v4→v5 even though net `available_beds` was unchanged (6 before and after).

Pass C verified already-pinned: shelter/unit creation field sets and `capacity_posture` thresholds; unit-label uniqueness and unit-list ordering; the full bed-ledger formulae; `settled_revenue_cents`; every list-filter set for units, screenings, admissions, cases, referrals and disclosures (§2.3 matches all six); the §4 authorized-role sets for all 24 endpoints in the partition; screening `APPROVE`'s three guards in frozen→shelter→caseload order; waitlist-position arithmetic; duplicate-admission-before-not-approved precedence; accessibility/composition/aggregate-window guards on both reserve and relocate in §2.7 order; both stay-cost variants; cancel's `ADMITTED`→`APPROVED` return and its no-promotion rule; the five-link compromise cascade; `ERR_SAME_UNIT_RELOCATION` and `RELOCATED` terminality; hearing-window validation, the 60-minute buffer with touching endpoints conflicting, the `FILED`-only calendar scope, and all three outcome branches; partner registration; referral creation's two guards; the pre-commitment tier/fee ordering and six-step ledger re-derivation; the disclosure field vocabulary, all four allowed sets, canonical-order emission, status derivation, the three release gates in order, and the `late_filed` strict-inequality rule.

### Orchestrator verification of Step 9

- `PRD_COMPLETED.md` is **not** byte-identical to `PRD_FINALIZED.md` (`cmp` differs; 60 lines revised) — the failure mode where the scan silently never runs did not occur.
- 530 lines / 125,930 chars; 25 headings intact; §4 has exactly 57 endpoint rows and §5 exactly 47 error rows; the file still ends at `| \`ERR_LANDLORD_NO_UNITS_AVAILABLE\` | 409 |`, so no pass truncated the document or dropped a table.
- Nothing under `workspace/implementation/` or in `test_suite/` / `test_helpers/` was modified after the green sweep at 07:55 (`find -newermt` returns empty), so the eight `results.{1..8}.json` files remain a valid record of the final code: 74/74 in all 8 rounds.

PIPELINE COMPLETE — Step 9 has written workspace/PRD_COMPLETED.md.
