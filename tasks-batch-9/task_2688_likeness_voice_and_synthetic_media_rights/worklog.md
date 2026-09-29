# Worklog — task_2688_likeness_voice_and_synthetic_media_rights

## Step 1: Create task directory — 2026-09-04T06:43:33.761Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2688_likeness_voice_and_synthetic_media_rights` and `.../workspace`. Index 2688 was pre-assigned by the orchestrating prompt; no scan of ./tasks/ was performed (concurrent pipelines on this host).

## Step: scaffold generation (§1.0-§1.9) — complete
- SCAFFOLD.yaml (3072 lines): §1.0-§1.7 only; 11 entities, 5 state machines, 2 OCC rules,
  50 endpoints, 54 errors, 5 roles. Three reachability repairs made during §1.9 review:
  priority 38 -> 84 carve-out (ERR_REVISION_LIMIT_REACHED), priority 36 -> 52 carve-out
  (ERR_ASSET_UNDER_LEGAL_HOLD), and validation 28 re-pointed at EstateAuthority.submitted_by_user_id
  (the old "drafted_by of a grant relying on it" wording was unreachable because grant creation
  already requires a VERIFIED authority).
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (1731 lines): 9 rules / 22 instances.
- SCAFFOLD_CORNER_DESIGN.yaml (3693 lines): 9 sections / 82 instances (54 recipes, 28
  excluded_because stubs). All 54 error ids triggerable across the two design files.
- scaffold_lint.py: VERDICT clean lint, 871 calls scanned.

## Step 2: Generate Scaffold (subagent) — 2026-09-04T08:29:30.000Z

(Verbatim subagent summary)

All three scaffold artifacts are complete and lint-clean.

Outputs (all under `tasks/task_2688_likeness_voice_and_synthetic_media_rights/`)

| File | Lines | Bytes | Contents |
|---|---|---|---|
| `SCAFFOLD.yaml` | 3072 | 166435 | §1.0–§1.7 only (verified: contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`). 11 entities, 5 state machines, 2 OCC rules, 8 calculations, 54 validations, 50 endpoints, 54 errors, 5 roles. Scenario text stored verbatim. |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1731 | 133379 | Single top-level key `scaffold_difficulty_design`; all nine §0.5 rules, 22 instances (2–3 each, >=2 everywhere). |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3693 | 276186 | Single top-level key `scaffold_corner_design`; all nine §1.9 sections, 82 instances = 54 full `test_recipe`s + 28 `excluded_because` stubs. |

Section breakdown of §1.9: entities 11, state_machines 16, calculations 16, validations 9, endpoints 6, errors 10, rbac 4, cross_cutting_complexity_layers 8, consistency_model 2. All 104 instance names across the two design files are unique.

Lint verdict (verbatim, final run)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    50
  §1.1 entities declared:     11
  §1.8 instances scanned:     22
  §1.9 instances scanned:     54
  Calls scanned (§1.8+§1.9):  871

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Key findings — three unreachable-error repairs to SCAFFOLD.yaml

Walking §1.9's "every error code is triggerable" requirement surfaced three error ids that the priority ladder made impossible to reach; each was fixed in the scaffold rather than papered over in the design files:

1. `ERR_REVISION_LIMIT_REACHED` — the fourth `REQUEST_REVISION` rejects instead of looping, so no performance is ever left in `REVISION_REQUESTED` at round 3. Added a priority 38 -> 84 carve-out: a resubmit of a performance already `REJECTED` with `rejection_reason == REVISION_LIMIT_REACHED` reports 84 instead of the generic state error.
2. `ERR_ASSET_UNDER_LEGAL_HOLD` (priority 52) was shadowed by priority 36, whose check demanded `status in {STORED, PURGE_SCHEDULED}`. Priority 36 now admits `LEGAL_HOLD` and defers to 52; only `PURGED` draws `ERR_INVALID_ASSET_STATE`.
3. `ERR_SEGREGATION_OF_DUTIES`'s estate leg said the verifier must differ from `ConsentGrant.drafted_by_user_id` — unreachable, since grant creation already requires a `VERIFIED` authority (priority 48). Re-pointed at `EstateAuthority.submitted_by_user_id`, matching what the endpoint description already promised. Four existing recipes were given explicit distinct submitter/verifier ids so they do not trip the now-live rung.

Verified programmatically at the end: all 54 catalog error ids appear in at least one design-file instance.

Orchestrator verification: `ls -la` confirms all three files present; `grep -c` for design keys in SCAFFOLD.yaml returns 0.

Note: the Step 2 subagent also appended its own short entry above this one (lines 7-17). Left in place per append-only rule.

## Step 3: Copy Shared Files — 2026-09-04T08:30:11.875Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD (subagent) — 2026-09-04T08:45:00.000Z

(Verbatim subagent summary)

PRD generation for task 2688 is complete and verified.

Deliverable: `workspace/PRD.md` — 454 lines, 14,520 words, 106,678 bytes, written in 13 incremental `cat >>` appends (absolute paths) to stay under the output cap.

Last section heading: `## 5. Error Code Catalogue` (line 395). The document ends at a real boundary: a complete 54-row error table whose final row is `| ERR_COMPENSATION_BELOW_STATUTORY_FLOOR | 422 |`. No mid-sentence or mid-table truncation, no audit footer, no contract reports inside the file.

Root cause of the earlier "impossible" contract diff: the checker was not a path problem — it was a backtick-pairing bug. The ```json fences in the verbatim §2.2 block introduce odd runs of backticks, which shifted every subsequent `([^`]+)` match by one, so real tokens landed in the "gaps." Stripping fenced code blocks before matching resolved it. PRD.md was never edited on the basis of the bad output.

Hard Contract 1 — Field-Name Coverage: PASS
| Source set | Required | Present | Missing |
| entities[].fields[].name (11 entities) | 128 | 128 | 0 |
| endpoint request-body fields | 76 | 76 | 0 |
| endpoint query params | 27 | 27 | 0 |
| operation output fields | 12 | 12 | 0 |
| errors[].id | 54 | 54 | 0 |
| state-machine state values (7 machines) | 35 | 35 | 0 |
| entity enum values | all | all | 0 |

Hard Contract 2 — Rule Coverage: PASS
- All 54 validations: every error_id appears in the §2/§3 narrative, not merely in the §5 table (0 table-only ids).
- Both concurrency rules documented in §2.8: expected_talent_version -> ERR_TALENT_VERSION_STALE (412) and expected_replica_version -> ERR_REPLICA_VERSION_STALE (412).
- All 9 calculations covered with formula semantics and every non-worked-example constant. Verified the only numerically "absent" values (12000000, 225000, 5520, 2029, 14, ...) are confined to worked_examples blocks, which are deliberately not copied; genuine constants such as the reach tiers (1,000,000 / 10,000,000), TERRITORY_STEP 0.10, media multipliers, surcharge rates 0.0175/0.0125, severity weights 0.60/0.25/0.15, REACH_SATURATION 10,000,000, and the 0.75/0.50 thresholds are all stated.
- Rounding disciplines pinned: royalties round_half_up once on the composed product; compliance surcharge ceil; share split rounds each share independently with the signed remainder swept into talent_share_cents.
- Sibling-branch symmetry preserved (revoke/reinstate, quarantine/release via held_from_status, provisional accrual vs. REVERSAL), plus all 5-hop cascades and the 5-phase compliance sweep.

Hard Contract 3 — §3 Path Purity: PASS. Scanned lines 174-337 (all of §3): 0 slash-paths inside backticks, 0 bare HTTP method tokens. Operations are named by state-transition pairs and role+action verbs. HTTP surface appears only in §2.8, §2.10 and §4, which is permitted.

Additional verification
- §4 endpoint table: 50/50 rows; method+path set matches SCAFFOLD.yaml exactly (0 missing, 0 extra) and 0 role mismatches across all 50 rows.
- §5: 54/54 error rows.
- §2.2 is byte-identical to skills/prd-bench-doc-generator/section-2.2-response-structure.md (PRD lines 31-78 == canonical 1-48), guaranteed by cat-ing the canonical file rather than retyping.
- Scope constraints honored: neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml was opened, grepped, or referenced; no sibling task directory was read. Only PRD.md was created in the task tree — no stray files, no worklog drift.

Scaffold inconsistencies resolved deliberately
1. closure_outcome — documented the transition-level vocabulary (LICENSED_USE_CONFIRMED, BELOW_ENFORCEMENT_THRESHOLD, VOLUNTARY_REMOVAL, SETTLED, LITIGATED) while the close request's outcome payload takes REMOVED/SETTLED/LITIGATED.
2. Source assets must be STORED at replica-build time, but the scaffold assigns no error id for the non-STORED/non-LEGAL_HOLD case — requirement stated without inventing a code.
3. scheduled_first_use_at must fall inside the grant term — likewise stated without an invented error id.
4. Suspension-time retention recomputation is documented as a no-op, since suspension does not move effective_end_actual.

Orchestrator truncation check (mandated by the invoking prompt): `wc -l` = 454; `grep -n '^## '` shows all 5 sections present (1. Introduction, 2. Global Specifications, 3. Business Logic & Workflows, 4. Endpoint Definitions, 5. Error Code Catalogue); `tail -12` ends on a complete markdown table row. NOT truncated — no regeneration needed.

## Step 5: Generate Unit Tests (subagent) — 2026-09-04T10:56:33.966Z

(Verbatim subagent summary; Steps 5 and 6 were launched concurrently in a single assistant message so the impl generator was physically isolated from test_suite/)

Generation is complete.

What was produced

`test_helpers/` — 9 modules, 2,542 lines: `__init__.py` (re-export surface), `api_client.py` (one method per endpoint plus `raw_get`/`raw_post`), `api_errors.py`, `assertions.py` (ledger splits, sweep reports, pagination, versions, postures), `constants.py`, `factories.py` (payload builders whose defaults match the design recipes exactly), `fixtures.py` (1,044 lines of scenario chains and tiered composites), `test_users.py`, `types.py`.

`test_suite/` — `conftest.py` plus 21 test modules, 7,392 lines, 140 tests.

Verification results
- Coverage: complete. 22/22 difficulty instances and 54/54 non-stub corner instances are translated — 76 distinct `Design:` tags, zero missing, zero tags pointing at a stub or non-existent instance. The 28 `excluded_because:` corner stubs were correctly not translated. Nothing was skipped under the PRD-first filter — every non-stub instance had verbatim PRD coverage that uniquely derived its asserted outcome.
- Citations: clean. Citation checker → `140 tests, 76 distinct design tags, 0 problems`. Every quoted span >=20 chars survives a literal whitespace-normalized grep of `workspace/PRD.md`; every test has exactly one `Design:` line and it is the last line of the docstring (AST-checked across all 140).
- No `skip`/`xfail`/`TODO`/placeholder markers, no mention of "scaffold", and the only remaining `§` references are inside verbatim PRD quotes (the PRD itself cross-references `§2.7`); the one instance of my own prose citing a section number was rewritten.
- `python3 -m pytest test_suite --collect-only -q` → 140 tests collected, no import errors. All 30 files byte-compile.
- Paths correct: `test_helpers/` and `test_suite/` exist at the task root; `workspace/` contains only `INSTRUCTION.md`, `PRD.md` and `implementation/`. `workspace/implementation/` and `worklog.md` were never touched, and `__pycache__` dirs left by the compile checks were removed.

Two notes for the caller
- Three enum values in `SCAFFOLD_CORNER_DESIGN.yaml` are not in the PRD's vocabulary and were translated to the PRD's actual values rather than copied: `replica_kind: "VOICE_CLONE"` → `VOICE`, and a pagination recipe's `rejection_reason: "off brand"` → `OFF_BRAND`.
- The suite has never been executed against an implementation (that is Step 7's job); the arithmetic in the assertions was derived by hand from the PRD's own worked examples (e.g. per-use 225000 → surcharge 3938 → total 228938; the six-entry 1,425,000 roll-up; severity 0.7500 vs 0.7470).

Orchestrator verification: `ls -d workspace/test_helpers workspace/test_suite` → none (no drift into workspace/); 22 entries in test_suite/.

## Step 6: Generate Implementation (subagent) — 2026-09-04T10:56:33.966Z

(Verbatim subagent summary)

The implementation is complete and verified.

Output: `workspace/implementation/` — 13 files, 3,132 lines:

| file | lines | role |
|---|---|---|
| `start.sh` | 10 | guarded pip install (`if ! python3 -c "import flask"`) + `exec python3 app.py` |
| `app.py` | 87 | blueprint registration, error envelope handlers, per-request lock |
| `core.py` | 567 | in-memory `Store`, logical clock, ISO-8601 helpers, Decimal rounding, 54-entry error catalogue, RBAC, validators, pagination |
| `calc.py` | 256 | the 9 calculations + all numeric constants |
| `services.py` | 614 | navigation, derived posture, append-only ledger, all cascades, 5-phase compliance sweep |
| `guards.py` | 193 | one helper per rung of the §2.10 rejection ladder |
| `routes_*.py` (7) | 1,405 | the 50 endpoints |

Verification
- Route parity: programmatic diff of the Flask URL map against the PRD §4 endpoint table → `ROUTES_MATCH` (50/50, method + path).
- Fresh boot: relaunched on a second port; all 10 collections report `total_count = 0`, so nothing is seeded. Storage is dicts only — a grep for `sqlite|open(|json.dump|pickle|/tmp|seed` returns only doc-comment hits.
- PRD worked examples reproduced exactly: initial creation `300000 x 1.15 x 1.25 x 1.35 → 582188` shape (verified via `900000 x 1.35 = 1215000`, topup 0); final royalty `150000 x 1.90 x 1.50 x 1.10 = 470250`, ADVERTISING surcharge ceil(8229.375) = `8230`, total `478480`; severity `0.925 / 6M views / CLEAR = 0.7500` and sweep case `1.000 / 0 views / RESTRICTED = 0.6900`; ledger split `600000 → 450000 / 120000 / 30000`.
- Error ladder spot-checked with status codes: 401 unauth and unknown role, 403 `ERR_ROLE_NOT_PERMITTED` / `ERR_NOT_LICENSEE_OWNER` / `ERR_SEGREGATION_OF_DUTIES` (both duties), 412 `ERR_REPLICA_VERSION_STALE`, 409 `ERR_DISCLOSURE_NOT_VERIFIED` / `ERR_REPLICA_OVERLAP_CAP_EXCEEDED` / `ERR_SEVERITY_BELOW_ESCALATION_FLOOR` / `ERR_ASSET_UNDER_LEGAL_HOLD` / `ERR_REPLICA_SOURCE_UNDER_LEGAL_HOLD` / `ERR_ASSET_BOUND_TO_ACTIVE_REPLICA`, 422 `ERR_DISCLOSURE_PLACEMENT_INSUFFICIENT` / `ERR_WINDOW_EXCEEDS_CONSENT_TERM` / `ERR_STATE_LAW_PROFILE_MISSING`, 400 money-as-string.
- Cascades exercised end to end: 5-hop escalation (asset → `LEGAL_HOLD` with `held_from_status`, replica → `QUARANTINED/SOURCE_LEGAL_HOLD`, performance → `WITHDRAWN` with a `REVERSAL` posted, license → `REMOVAL_PENDING/REPLICA_QUARANTINED`, talent → `FROZEN`); closure released holds back to exactly `held_from_status` and posture fell to `RESTRICTED` while an obligation stayed open; death cascade suspended the grant as `DEATH_PENDING_ESTATE` and estate verification released it; sweep phases 1-5 including `purge_scheduled_count → purged_count` seven days later and a fully-zero idempotent second pass at the same instant.

One design change made this session: `core.touch()` now applies the `version` bump immediately (idempotent per request via a `g._touched` id set) rather than deferring to an `after_request` flush — a deferred flush would have serialized stale version counters into every response body. `flush_touches()` was removed; nothing referenced it.

Notes for the orchestrator
- Two behaviours follow the PRD literally where it under-specifies: a sweep-opened case copies `suspect_url` from `distribution_reference`, so a license that never went live yields `suspect_url: null`; and `detected_view_count` defaults to 0 on sweep cases since §3.11 does not name it.
- `PER_USE_FINAL` ledger entries name `usage_license_id` only (not `generated_performance_id`), per §2.6's split of "raised against a submitted output" vs "raised at license issuance".
- No `test_helpers/` or `test_suite/` was read or created; `worklog.md` untouched. Both smoke ports (8741, 8742) were killed by recorded PID / port-resolved PID and are free — no broad pkill was ever issued.

## Step 7: Run Tests and Iterate (long-lived subagent) — 2026-09-04T11:22:00.000Z

(Verbatim subagent summary)

All 8 parallel rounds are green: 140 passed / 140 total in every round.

Iterations run: 3 sweeps (baseline 101/140 deterministic in all 8 rounds → 139-140/140 with one flake → 140/140 in all 8).

Tests deleted: none. Two *assertions* were removed under PRD-silence (STEP 1c partial coverage), both on the same silent field:
- `test_suite/test_17_error_identity.py` — `assert purged["purge_note"] == first_note` and `assert unchanged["purge_note"] == first_note`
- `test_suite/test_18_error_precedence.py` — `assert intact["purge_note"] is None`

  Category: attribute silence. PRD §3.5 mentions `purge_note` only as an *input* ("destroys the sample ahead of schedule, supplying a `purge_note`"); no sentence makes it a response-visible `BiometricAsset` attribute, and §3.5's enumeration of the asset's fields (`purge_due_at`, `purged_at`, `held_from_status`) omits it. A faithful reader would correctly leave it out of the serializer. (Replaced with `payload_digest` checks already covered verbatim by PRD.)

Fixes applied to `test_suite/` (all made the test *more* faithful to PRD):
- `test_15_validation_gates.py::test_a_missing_source_list_is_malformed_...` — the duplicate-source probe duplicated an asset belonging to the *other* grant, so the PRD-correct answer was `ERR_ASSET_CONSENT_MISMATCH` (§2.10 ranks it above `ERR_NO_SOURCE_ASSETS`). Now duplicates the same-grant asset.
- `test_16_endpoint_surfaces.py` — `assertions.assert_timestamp_format` → the re-exported `assert_timestamp_format` (the symbol lives in the runner's testing package, not in `test_helpers.assertions`); and `_two_profiles_on_the_books()` now advances the logical clock one day between the two registrations, so `created_at` genuinely differs. Both profiles previously shared the startup instant, leaving the "newest first" assertion at the mercy of the `id` tiebreak whose direction PRD does not state — that was the round-2/3/5/6/7 flake.
- `test_18_error_precedence.py` — `fixtures.refresh_talent(...)` → `fixtures.read_talent(...)` (`refresh_talent` returns the scenario, not the talent → `KeyError: 'id'`).
- `test_19_role_boundaries.py`, `test_20_cross_cutting_layers.py` — `assert_version_advanced_by(record, baseline, 1)` was passed the whole record as `baseline` → `TypeError: dict + int`; now passes `baseline["version"]` / `before["version"]`.
- `test_21_consistency_model.py` — `assert refused.status_code == 422` → `409`; PRD §5 maps `ERR_REPLICA_OVERLAP_CAP_EXCEEDED` to HTTP 409.

Fixes applied to `implementation/`:
- `workspace/implementation/core.py` — timestamp rendering split (the single root cause of 30 of the 39 baseline failures). The old `iso()` stamped *every* datetime with three fractional digits. PRD scopes that format to `created_at`/`updated_at` (§2.4) and `api_request_timestamp` (§2.2), while writing every logical-clock stamp and whole-day deadline verbatim without a fraction — `2026-08-01T00:00:00Z` for the clock default (§2.5), `2090-03-15T00:00:00Z` for `postmortem_rights_until` (§3.1), `2027-08-01T00:00:00Z`/`2026-10-15T00:00:00Z`/`2027-01-28T00:00:00Z` for `retention_until` (§3.5), `2027-08-16T00:00:00Z`/`2027-08-23T00:00:00Z` for `removal_deadline` (§3.9), `2060-03-15T00:00:00Z` for `use_state_rights_until` (§3.10). Added `iso_ms()` (three fractional digits, used for `created_at`, `updated_at`, `api_request_timestamp`) and redefined `iso()` at whole-second resolution, falling back to three digits only for a sub-second instant a caller could drive the clock to. No behavioural logic changed.

`test_helpers/` needed no changes.

Orchestrator verification (mandated — a Step 7 subagent can claim a clean sweep without leaving artifacts): all 8 `workspace/implementation/results.{1..8}.json` exist (~42.6 KB each, timestamped 11:22) and each parses to `passed=140 total=140 failed=0`. Confirmed green independently.

Step 8 is NOT skipped: Step 7 applied 1 `implementation/` fix and 6 `test_suite/` fixes.

## Step 8: Finalize PRD (subagent) — 2026-09-04T11:30:00.000Z

(Verbatim subagent summary. Step 8 ran because Step 7 had non-zero fixes.)

PRD_FINALIZED.md is written. Verified: 456 lines, `## 5. Error Code Catalogue` at line 397 with all 54 error rows intact and the file ending on `ERR_COMPENSATION_BELOW_STATUTORY_FLOOR | 422`.

Line counts: `PRD.md` 454 lines → `PRD_FINALIZED.md` 456 lines (+2 lines, +0.44%). Three hunks total, no sections added or removed.

Changes
- §2.4 (Resource Identity, Timestamps and Version Counters) — insert — timestamp rendering split — added one paragraph pinning that `created_at`/`updated_at` (and `api_request_timestamp`) are the only instants written with a fraction, and that every other instant returned in `data` is whole-second with no fractional digits, falling back to three (millisecond-truncated) digits only for a sub-second instant reachable by driving the clock there — `implementation/core.py:82-111` (`iso_ms`/`iso`), `core.py:114` (`MILLISECOND_FIELDS`), `core.py:258` (`public`), `core.py:247`, `services.py:613`, `routes_reference.py:160`.
- §2.3 (Pagination, Filtering and List Ordering) — revise — state-law-profile list tiebreak — "then by `id`" → "then by `id` ascending" — `implementation/core.py:583-584` (`order == "created_desc_id"`), reached only from `routes_reference.py:70-71`.
- §3.5 (Biometric Custody...) — revise — `purge_note` is request-only — clause added: mandatory non-blank free text, validated but not retained, absent from the asset's representation — `implementation/routes_asset.py:86` (validated, never stored) + `core.py:251-265` (`public` serialises only stored keys).

No PRD edits were made for the five remaining `<step_7_diff>` items: test_15's duplicate-source probe (PRD §3.6 + §2.10 already fix `ERR_ASSET_CONSENT_MISMATCH` above `ERR_NO_SOURCE_ASSETS`, and `routes_asset.py:125-135` evaluates in exactly that order), test_16's `assert_timestamp_format` import, test_18's `refresh_talent`→`read_talent`, test_19/20's `assert_version_advanced_by` baseline argument, and test_21's 422→409 (PRD §5 already maps `ERR_REPLICA_OVERLAP_CAP_EXCEEDED` to 409). All five were test/fixture defects, not PRD silence or mismatch.

Per-edit pre-edit search log

Edit 1 — subject: rendering format of every ISO 8601 instant in a response.
(b) Enumerated/read: `core.py:82-111` (`iso_ms`, `iso` incl. the microsecond fallback), `core.py:114` (`MILLISECOND_FIELDS = created_at, updated_at`), `core.py:251-265` (`public()` — the single serialiser for every stored row), `core.py:242-248` (`_meta` → `api_request_timestamp` via `iso_ms`, wall clock); grep for every non-`public` response body (`grep respond( routes_*.py app.py | grep -v public` → only `routes_reference.py:147` sweep report and `:160` `current_utc`, both `iso()`); `services.py:613` (`run_at` via `iso`); every datetime-valued row key across `routes_talent.py:107,141` (`verified_at`), `routes_consent.py:130,142,189,264` (`effective_from/until`, `countersigned_at`, `effective_end_actual`), `routes_asset.py:55-58,101,193` (`retention_until`, `purge_due_at`, `purged_at`, `approved_at`), `routes_perf.py:35,71,74,196` (`scheduled_first_use_at`, `review_deadline`), `routes_license.py:29,105,118,120,240` (`distribution_start/end`, `removal_deadline`, `removal_confirmed_at`), `routes_case.py:98` (`takedown_issued_at`), `services.py:175` (`posted_at`), `services.py:458` (`use_state_rights_until`), `calc.py:191-214` (`at_midnight`/`add_days`/`add_years` deadline producers).
(c) Wording adjustments made: (i) scoped the claim to instants "returned inside `data`" so it cannot contradict §2.2's three-digit `api_request_timestamp` in `meta`; (ii) used category language ("every logical-clock stamp on a resource, every computed deadline or expiry, every client-supplied instant echoed back") instead of a field-name list, so no field is accidentally omitted or misnamed; (iii) kept the sub-second fallback clause because `retention_until = add_days(created_at, N)` and similar deadlines inherit a driven clock's microseconds and would then render with three digits — a flat "never fractional" claim would have been false.

Edit 2 — subject: ordering of the `GET /state-law-profiles` collection, specifically the `id` tiebreak direction.
(b) Enumerated/read: `core.py:579-592` (`collection`, all four order modes), `core.py:583-584` (the `created_desc_id` double sort — `id` ascending first, then a *stable* descending sort on `created_at`, so equal `created_at` preserves `id` ascending), `core.py:575-577` (`by_created_asc`, the default), grep for `created_desc_id` → only `routes_reference.py:71`; also checked the other two special orders (`effective_from_asc`, `posted_at_asc`) are untouched by this wording since the sentence names only the profile clause.
(c) None — "ascending" is the one word added and it matches the only callsite; the sibling clauses in the same sentence were left verbatim.

Edit 3 — subject: the `purge_note` field on the manual biometric-asset purge.
(b) Enumerated/read: `routes_asset.py:82-103` (whole purge handler: `want_str(body, "purge_note", 1, None)` → required, non-blank, no max length, return value discarded), `core.py:359-373` (`want_str` semantics for `min_len=1`/`required=True`), `core.py:251-265` (`public()` iterates stored keys only, so a never-stored key is absent rather than null), `services.py:596-606` (sweep's automatic purge path — never touches `purge_note`), `services.py:225-250` (deadline recompute — untouched), and a repo-wide grep for `purge_note` in `implementation/` confirming `routes_asset.py:86` is its only occurrence. Also compared the sibling notes to avoid over-claiming: `approval_note` (`routes_asset.py:181`, optional, discarded), `revocation_note` (`routes_consent.py:253`, required, discarded), `escalation_note` (`routes_case.py:119`, required, discarded), `review_note` (`routes_perf.py:77,114,131`, optional and stored, as PRD §3.7 already says).
(c) Wording adjustments made: confined the claim to `purge_note` and to "the asset record" only — no generalisation about notes elsewhere, since `review_note` genuinely is persisted; and said "absent from the asset's representation" rather than "null", matching the serialiser (the key never exists) and the assertion Step 7 removed from `test_18`.

Orchestrator verification: `wc -l` 454 → 456; `diff PRD.md PRD_FINALIZED.md` shows exactly the three described hunks (§2.3 tiebreak word, §2.4 inserted paragraph, §3.5 purge_note clause) and nothing else; tail confirms the §5 error table still ends intact.

## Step 9: Complete PRD (3 sequential module-partitioned subagent passes) — 2026-09-04T11:54:44.249Z

Orchestrator decision (recorded per the AUTONOMY instruction): Step 9 was run as THREE sequential passes over one shared `PRD_COMPLETED.md`, partitioned by implementation module, rather than one subagent scanning all 3,132 impl lines against a 456-line PRD. A single pass reliably under-scans a partition this size; the failure signature is a `PRD_COMPLETED.md` byte-identical to its source. Pass 1 did the `cp`; passes 2 and 3 were explicitly forbidden from copying so they could not clobber earlier work. Partition: pass 1 = app.py/core.py/calc.py/guards.py; pass 2 = services.py/routes_talent.py/routes_consent.py/routes_asset.py; pass 3 = routes_perf.py/routes_license.py/routes_case.py/routes_reference.py.

### Pass 1 (app.py, core.py, calc.py, guards.py) — verbatim summary

Source `PRD_FINALIZED.md`: 456 lines / 107,593 chars → `PRD_COMPLETED.md`: 457 lines / 113,426 chars (char delta +5,818; the single added line is one new bullet inside the existing §2.2 error-format bullet list — no new sections, all 26 headers preserved).
`## 5. Error Code Catalogue` still has all 54 rows (line 398). Verified programmatically against `core.py ERROR_HTTP`: same 54 identifiers, same HTTP statuses, same order.
Counts: ambiguity-pins 15, mismatch-revisions 1 (§2.10's blanket "required arrays non-empty").

- §2.1 — revise — ambiguity — a present-but-blank/whitespace `X-User-ID` is `ERR_UNAUTHENTICATED`, not merely an absent one — core.py:303
- §2.2 success bullets — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric chars — core.py:243
- §2.2 success bullets — revise — ambiguity — `api_request_timestamp` comes from real wall-clock time, the only response instant not from the logical clock — core.py:244
- §2.2 error format — insert — ambiguity — unrouted path → `ERR_INVALID_REQUEST`/404, bad method → /405, unparseable JSON → /400, unhandled failure → /500; trailing slash insignificant — app.py:56-77, 26
- §2.3 P1 — revise — ambiguity — empty-string `limit`/`offset` treated as absent; non-exact integer literals (`10.0`, `+10`, `010`) malformed — core.py:529-548
- §2.3 P2 — revise — ambiguity — every list ordering breaks residual `created_at` ties by server creation sequence (state-law profiles excepted, already `id` asc) — core.py:576,586,588
- §2.3 P3 — revise — ambiguity — filters compare stringified field values; empty-string filter ignored; unmatched value yields empty page not error — core.py:564-572
- §2.4 — revise — ambiguity — `version` advances at most once per request even when several cascade hops touch the row, while `updated_at` refreshes each touch — core.py:316-332
- §2.5 — revise — ambiguity — client instants normalised to UTC; naive value read as UTC; date-only read as `00:00:00Z` — core.py:57-79
- §2.6 — revise — ambiguity — over-precision percentage rejected; percentages echoed as JSON numbers (0.20 → `0.2`) — core.py:450-451, 259-260
- §2.7 — revise — ambiguity — union-row selection tie beyond equal `effective_from`+`created_at` goes to the row registered first — calc.py:101-104
- §2.10 payload rung — revise — MISMATCH — explicit `null` == omitted (required → missing, optional → default); absent/empty body == `{}`; non-object or unparseable body rejected here; integer-valued floats accepted, strings never; `source_asset_ids` carve-out (>10 malformed here, empty/duplicate deferred to `ERR_NO_SOURCE_ASSETS`) — core.py:340-352, 355-357, 393-402, 507-520
- §2.11 — revise — ambiguity — requests are serialised, so a cascade is never observed half-applied — app.py:37-50
- §3.3 — revise — ambiguity — all countersign conditions (grantor kind, `LIVING`, identifier match, authority `VERIFIED` + matching `talent_id`) are ownership-rung, so they draw `ERR_NOT_TALENT_REPRESENTATIVE`/`ERR_NOT_ESTATE_REPRESENTATIVE` rather than a state error — guards.py:116-130
- §3.4 — revise — ambiguity — on revoke, `grantor_kind` picks which identifier must match but the caller's role picks which ownership error is reported; estate side additionally needs a `VERIFIED` authority for that talent — guards.py:133-150
- §3.10 — revise — ambiguity — severity score carried as a JSON number (0.7500 renders `0.75`); `use_state_rights_until` also null for a talent with no `date_of_death`, stored at `00:00:00Z` — core.py:259-260, calc.py:245-256

Note: every numeric constant in `calc.py` (breadth 0.15, duration 1.00/1.25/1.60 at <=12/<=36 months, exclusivity 1.35, media multipliers, reach tiers/factors, territory 0.10, 7-day grace and review windows, 3-round cap, 30-day term, overlap cap 2, surcharges 0.0175/0.0125, weights 0.60/0.25/0.15, 10M saturation, 0.7500 takedown, 0.5000 escalation, posture factors, 0.5 union-floor ratio, disclosure ranks) already matched the PRD exactly and required no edits.

### Pass 2 (services.py, routes_talent.py, routes_consent.py, routes_asset.py) — verbatim summary

Line count: 457 before → 457 after (every change in-paragraph; no new paragraphs, no new sections). Chars 113,426 → 119,175 (+5,749). §5: 54 rows intact. §4 endpoint table still 50 rows. Pass 1 edits verified present (5 spot-checks matched). Counts: 19 ambiguity-pins, 4 mismatch-revisions.

- §2.6 — insert — ambiguity — an entry's `posted_at` is always the same instant as its own `created_at` — services.py:160,175
- §2.6 — insert — ambiguity — no `REVERSAL` row is written when `provisional_compensation_cents` is already zero or the entry was already reversed; the field is just cleared — services.py:193
- §2.6 — insert — ambiguity — a roll-up refresh is not itself a mutation: appending an entry moves the grant's `total_compensation_cents` and the talent's `lifetime_compensation_cents` without advancing either `version`/`updated_at` — services.py:179-185
- §2.11 — insert — ambiguity — a recomputation that finds nothing changed is not a touch (talent counters/posture, replica `open_license_count`) — services.py:113-124,140-142
- §3.1 — insert — ambiguity — a future `date_of_death` draws `ERR_INVALID_REQUEST` on the payload rung, ahead of `ERR_TALENT_NOT_FOUND`; the instant is stored as supplied while the derived expiry collapses to whole days — routes_talent.py:70-72,79
- §3.1 — insert — ambiguity — `registration_number` is 1 to 120 characters non-blank; a claim may be filed against a talent in either `life_status` (no talent-state gate) — routes_talent.py:91,93
- §3.1 — insert — ambiguity — the registration copy at verification is unconditional; a null `registration_number` overwrites an earlier one — routes_talent.py:145
- §3.2 — insert — ambiguity — a `grantor_kind`/`estate_authority_id` breach is `ERR_INVALID_REQUEST`; the named authority need only exist (not `VERIFIED`, not this talent's), and `life_status` does not restrict `grantor_kind` — routes_consent.py:56-63
- §3.4 — revise — ambiguity — reinstatement of a `DEATH_PENDING_ESTATE` suspension without a `VERIFIED` authority draws `ERR_ESTATE_AUTHORITY_UNVERIFIED`; the authority consulted is the earliest created — routes_consent.py:228-231, services.py:77-81
- §3.4 — insert — ambiguity — `revocation_note` is mandatory non-blank, unbounded, and not retained on the grant — routes_consent.py:253
- §3.4 — insert — ambiguity — revocation hop one also clears `suspension_reason` to null — routes_consent.py:265
- §3.4 — insert — ambiguity — `open_license_count` is recomputed as licenses in `ISSUED`, `LIVE` or `REMOVAL_PENDING`, so opening an obligation leaves the count unchanged — services.py:86,135-142
- §3.5 — insert — ambiguity — `talent_id` and `consent_grant_id` are not cross-checked at asset registration; a mismatch only surfaces at replica build as `ERR_ASSET_CONSENT_MISMATCH` — routes_asset.py:36-40
- §3.5 — insert — ambiguity — only an asset whose recomputed `retention_until`/`purge_due_at` actually moves is treated as mutated — services.py:236-249
- §3.6 — revise — MISMATCH — PRD claimed every source asset "must be in `STORED` status at build time"; impl refuses only `LEGAL_HOLD`, accepting `PURGE_SCHEDULED` and even `PURGED` members — routes_asset.py:125-135
- §3.6 — insert — ambiguity — `approval_note` must be non-blank when supplied and is not retained — routes_asset.py:181
- §3.11 — insert — ambiguity — sweep phase one also clears `suspension_reason` to null — services.py:503
- §3.11 — revise — MISMATCH — phase one recomputes deadlines for every non-`PURGED` asset including `LEGAL_HOLD` (PRD had listed only `STORED`/`PURGE_SCHEDULED`), with `purge_due_at` alongside — services.py:506 → 233-246
- §3.11 — insert — ambiguity — phase two increments both `expired_license_count` and `removal_pending_count` for the same population; no other phase touches the latter — services.py:531-532
- §3.11 — revise — MISMATCH — phase three skips a license already `NON_COMPLIANT`, so a re-run neither re-stamps it nor opens a second case — services.py:546
- §3.11 — insert — ambiguity — the sweep-opened case carries `detected_view_count` of zero, a `suspect_url` that is null when the license never went live, and a severity posture term read from the pre-sweep posture — services.py:558-566, 608-609
- §3.11 — revise — MISMATCH — PRD said a scheduled asset "is therefore only destroyed by a later run"; the second step re-reads the store, so an asset over seven days past `retention_until` is scheduled AND purged in the same run, counting in both counters — services.py:590-599
- §3.11 — insert — ambiguity — `sweep_id` is a freshly generated prefix-free UUID belonging to no persisted row — services.py:479

### Pass 3 (routes_perf.py, routes_license.py, routes_case.py, routes_reference.py) — verbatim summary

457 lines before and after; 119,175 → 122,030 chars (+2,855). §5: 54 rows. §4: 50 rows. Pass 1 edits intact (3 spot-checks) and pass 2 edits intact (3 spot-checks). Counts: 3 mismatch-revisions, 11 ambiguity-pins (14 edits).

- §2.1 — revise — MISMATCH — dropped `issued_by_user_id` from the `RightsAdministrator`-recorded list; only a `LicenseeProducer` can ever issue a license — routes_license.py:23,121
- §2.1 — insert — MISMATCH — `LicenseeProducer` paragraph now states the issuing producer's identifier is recorded as the license's `issued_by_user_id` — routes_license.py:121
- §2.5 — insert — ambiguity — clock returns `current_utc` and nothing else in `data`, and may be wound backwards as freely as forwards — routes_reference.py:150-160
- §2.7 — insert — ambiguity — a direct read of a state law profile / union minimum row by an unknown `id` answers `ERR_STATE_LAW_PROFILE_MISSING` / `ERR_UNION_SCHEDULE_MISSING` (422), not a 404 — routes_reference.py:58-64,100-106
- §3.7 — revise — MISMATCH — `scheduled_first_use_at` is recorded as supplied and NOT validated against the grant's term (PRD had claimed it must fall inside it) — routes_perf.py:35,71
- §3.7 — insert — ambiguity — `review_note` bounds (1-500), `rejection_reason` optional even on `REJECT` (null when omitted), and `review_note` written on every decision so omission nulls an earlier note — routes_perf.py:114-116,131
- §3.7 — insert — ambiguity — `PER_USE_PROVISIONAL` (and its reversals) name the performance via `generated_performance_id`, leaving `usage_license_id` null — routes_perf.py:85,151,198
- §3.7 — insert — ambiguity — resubmission leaves `review_note` standing while clearing `reviewed_by_user_id` — routes_perf.py:191-196
- §3.8 — insert — ambiguity — `distribution_end` earlier than `distribution_start` is `ERR_INVALID_REQUEST` on the payload rung, ahead of the performance existence check — routes_license.py:33-36
- §3.8 — insert — ambiguity — the channel→media mapping is pinned: `ADVERTISING`→`ADVERTISING`, `ENTERTAINMENT`→the performance's own `media_type` — routes_license.py:59
- §3.8 — insert — ambiguity — the union floor at issuance is looked up on the parent performance's `media_type`, never the channel-mapped media type — routes_license.py:42
- §3.8 — insert — ambiguity — media multiplier and floor keep reading the performance's `media_type` (so `ADVERTISING`-channel over `EPISODIC` prices at 1.15); `PER_USE_FINAL` names the license via `usage_license_id` with `generated_performance_id` null — routes_license.py:91-92,125-127
- §3.9 — revise — MISMATCH — `disclosure_label_text` is mandatory (PRD read as optional via "non-blank when supplied") — routes_license.py:159
- §3.9 / §3.10 — insert — ambiguity — confirm-removal carries no payload fields; `escalation_note` is mandatory non-blank unbounded text, validated but not retained on the case — routes_license.py:231, routes_case.py:119

Not changed (verified already uniquely pinned): all four modules' role sets and filter keys against §2.3/§4; go-live's four gates plus both posture gates; disclosure-verification's single `LABELED` gate; triage's mandatory-takedown threshold and its non-enforceable carve-out; closure's outcome/state matrix and hold-release-only-when-no-other-escalated-case rule; the escalation cascade's five hops; profile/union field ranges and the three orderings in §2.3.

### Orchestrator verification of Step 9

- `wc -l -c`: PRD.md 454 / 106,678 → PRD_FINALIZED.md 456 / 107,593 → PRD_COMPLETED.md 457 / 122,030 (+14,437 chars over FINALIZED).
- `cmp -s PRD_FINALIZED.md PRD_COMPLETED.md` → differs, 97 changed lines. NOT byte-identical, so the scan genuinely ran (the known failure mode where a Step 9 subagent only performs the `cp` did not occur).
- All 5 sections present (`## 1` … `## 5` at lines 3/11/177/341/398); file ends on the complete final row of the §5 error table.
- Totals across the three passes: 45 ambiguity-pins, 8 mismatch-revisions, 53 edits.
- `implementation/` was not modified by Step 9, so the verified 8/8 green sweep from Step 7 (140/140 in every round) still stands. Pipeline complete.
