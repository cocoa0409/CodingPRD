# Worklog — task_1570_livestock_health_certificate_interstate

## Step 1: Create Task Directory — 2026-08-13T22:47:06.340Z

RESUME RUN: task directory `tasks/task_1570_livestock_health_certificate_interstate/` already existed from the killed prior run; treated as DONE per resume instructions (no index scan, no new directory).

Resume audit findings (before any generation):
- `SCAFFOLD.yaml` (1368 lines, 77KB) present but had 12 YAML flow-sequence syntax errors (`field?` unquoted inside `input: [...]` lists). Repaired by double-quoting only the `?`-suffixed items (14 line rewrites, values unchanged). Post-repair: parses cleanly; §1.1–§1.7 structurally complete (10 entities, 9 state machines, 2 concurrency rules, 6 calculations, 11 validations, 41 endpoints, 51 errors, 5 roles; natural EOF at roles section).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1149 lines, 70KB) present but had 1 YAML flow-mapping syntax error (line 530: `captures: { rec_status: $.data[0].status }` — unquoted `[` in flow mapping). Repaired by quoting the scalar. Post-repair: parses cleanly; structurally complete per §1.8 spec (all 9 difficulty rules × 2 instances, no truncation).
- `SCAFFOLD_CORNER_DESIGN.yaml` MISSING — never written by the prior run.
- `workspace/` empty (no INSTRUCTION.md, no PRD.md); no test_helpers/, test_suite/, or implementation/.

Conclusion: prior run died during Step 2 after writing 2 of 3 scaffold artifacts. Resume point = Step 2 completion (generate SCAFFOLD_CORNER_DESIGN.yaml only; reuse the two repaired files).

## Step 2: Generate Scaffold — 2026-08-13T23:39:17.262Z

RESUME NOTE: SCAFFOLD.yaml and SCAFFOLD_DIFFICULTY_DESIGN.yaml were reused from the prior run after minimal syntax repair (see Step 1 entry). The subagent below generated ONLY the missing SCAFFOLD_CORNER_DESIGN.yaml against those two frozen artifacts. Verbatim subagent summary:

Task complete. `/home/ubuntu/github/CodingPRD/tasks/task_1570_livestock_health_certificate_interstate/SCAFFOLD_CORNER_DESIGN.yaml` is written; the two frozen artifacts were not touched.

**Summary for worklog:**

- **Instance counts per claim-extraction-guide section** (70 real test_recipe instances + 21 `excluded_because:` stubs = 91 total): entities 17 real + 2 stubs; state_machines 39 real + 6 stubs; calculations 3 real + 8 stubs; validations 5 real + 5 stubs; rbac 3 real; cross_cutting_layers 2 real (both OCC rules: `permit_adjust_stale_version_rejected`, `entry_requirement_amend_stale_version_rejected`); consistency_model 1 real (`immediate_mutation_visibility_in_response`). Every stub cites an exact §1.8 instance name (verified to exist in SCAFFOLD_DIFFICULTY_DESIGN.yaml). Error-catalog cross-check: all 51 §1.6 error codes are triggered by at least one instance across the two design files.

- **Placeholder closure and call-by-call replay**: verified mechanically (script over the parsed YAML): zero unbound `${var}`, zero rebound capture names, all captures resolve to §1.5 `output:` fields (error-id captures use the §1.0 error envelope `$.data.error_id`, the same convention as the frozen §1.8 file), all OCC `expected_*_version` payloads are `${var}`-bound (never literals), all payload keys ⊆ endpoint `input:`, all calls resolve to §1.5 endpoints. Semantic replay against §1.2/§1.4/§1.6 was done per chain; two reachability subtleties found and resolved by restructuring (not by editing the frozen scaffold):
  1. `ERR_OUTBREAK_MOVEMENT_RESTRICTION` is normally masked by `ERR_PREMISES_DISEASE_HOLD` (escalation cascade holds the premises, priority 7b < 7d). Resolved by escalating the zone *before* registering the premises — the cascade is not retroactive, so the new premises stays MONITORED and the 7d zone gate surfaces at movement scheduling (`movement_blocked_by_active_zone_for_new_premises`).
  2. `ERR_VET_NOT_CURRENT` at *issue* required the vet to be current at submit but not at issue — resolved via the inclusive-expiry boundary (`veterinarian_credential_expiry_boundary`: issue at clock == accreditation_expires_at succeeds; submit one day later fails).

- **YAML validity**: confirmed — `python3 yaml.safe_load` parses cleanly; single top-level key `scaffold_corner_design:`; all risky scalars double-quoted or block style (no flow collections containing `?`/`[`/`: `).

- **No §1.5 reachability gaps required the priority ladder**: every precondition was reachable by composing existing declared endpoints (rung 1 of the ladder); the frozen SCAFFOLD.yaml needed no edits.

## Step 3: Copy Shared Files — 2026-08-13T22:47:52.690Z

Copied ./INSTRUCTION.md → tasks/task_1570_livestock_health_certificate_interstate/workspace/INSTRUCTION.md (1424 bytes). (Executed while Step 2-completion subagent runs; independent artifact.)

## Step 4: Generate PRD — 2026-08-13T23:44:54.941Z

The PRD has been generated and all three hard contracts verified. Final report:

## Task Complete

**Output written:** `/home/ubuntu/github/CodingPRD/tasks/task_1570_livestock_health_certificate_interstate/workspace/PRD.md`

**Structure:** §1 Introduction (3 paragraphs, business-context angle) → §2 Global Specifications in 10 domain-derived subsections (RBAC with per-role identity translation, verbatim §2.2, pagination, logical clock & lazy expirations, 11-layer validation pipeline, common resource properties, money/precision with pinned per-line rounding, OCC, certificate validity & whole-day age conventions, issuance sequences & SHA-256 digest) → §3 Business Logic in 8 subsections organized by lifecycle (reference data, lab testing & infection cascade, drafting/revision, review/issuance/fees, permits & shipment tracking, outbreak zones & hold/restore cascade, quarantine & segregation of duties, transmission audit trail) → §4 endpoint table (4 columns, 41 rows) → §5 error catalogue (2 columns, 52 entries). Document ends at §5 with no audit footer.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: ~58 unique required, 58 present, 0 missing
- endpoints[].request_body: 6 unique endpoint-only inputs (to_iso8601, current_utc, reason_code, reason, result, channel, expected_permit_version, expected_requirement_version) — all present, 0 missing
- endpoints[].query_params: 7 unique (destination_state_code, species_code, status, limit, offset, vet_id, origin_premises_id, test_record_id) — all present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 11 checked, 11 expressed in prose (§2.5 pipeline with explicit ordering and sub-orderings), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (expected_permit_version → ERR_STALE_PERMIT_VERSION/412; expected_requirement_version → ERR_STALE_REQUIREMENT_VERSION/412; no race framing), 0 missing
- state_machines[].transitions: 41 checked across 9 state machines, 41 fully expressed (all preconditions paired with error_ids, all side effects and cascades stated), 0 missing
- calculations[]: 6 checked, 6 fully expressed (cvi_issuance_fee provisional/final variants with all constants; movement fee with pinned round-before-sum; committed/projected headroom incl. 20-vs-14/20 worked example; 30-day validity with strict-greater lapse; whole-day floor ages with inclusive bounds; inventory derivation), 0 missing
- validations[] conditions: 11 checked, 11 matchable to error_ids in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 41 checked, 41 expressed, 0 missing
- entities[].fields[] structured content: all defaults, nullability, immutability, and computed-field derivations reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked (ISSUED/TRANSMITTED block branches, resolve from MONITORING vs CONTAINED, NEGATIVE vs POSITIVE, cancel from SCHEDULED vs IN_TRANSIT, etc.), 8 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: all field/state/enum/error tokens
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All three contracts PASS. §2.2 was emitted byte-for-byte verbatim from the skill's canonical source file. The forbidden difficulty-design and corner-design files were not opened, and no sibling task directories were inspected.

## Step 6: Generate Implementation — 2026-08-13T23:55:48.489Z

(Launched concurrently with Step 5 in a single orchestrator message; finished first.)

All files in place. start.sh is executable, guards pip install with an import check (per-test reboot safety), uses `exec` for foreground operation, and app.py binds `0.0.0.0:$PORT` (default 10000).

## Report

**Generated implementation** at `/home/ubuntu/github/CodingPRD/tasks/task_1570_livestock_health_certificate_interstate/workspace/implementation/`:

- **`start.sh`** — foreground bash launcher; guards `pip install` behind `python3 -c "import flask"` so per-test-server reboots skip the install; `exec python3 app.py`.
- **`requirements.txt`** — `flask>=3.0`.
- **`app.py`** (~1300 lines, single module) — complete Flask implementation of all 30 endpoints from the scaffold:
  - Logical clock (`POST /_clock/set_current_utc`) starting at `2026-08-01T00:00:00Z`; never falls back to wall clock.
  - Lazy materialization of `Certificate -> LAPSED` (with `pre_block_status` cleared when lapsed from `ENTRY_BLOCKED`) and `QuarantineOrder -> EXPIRED` (with premises re-evaluation) on first read/write after the clock passes the threshold.
  - Response envelope exactly per scaffold: `meta.{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}`, `response_type: object|array|error`, `data` wrapper; error body `{error_id, message}`.
  - Auth via `X-User-ID` + `X-User-Role`; all five roles enforced per endpoint table; `AccreditedVet` identity resolves to a `Veterinarian` row (404 `ERR_VETERINARIAN_NOT_FOUND` otherwise); ownership checks direct (`cert.vet_id`) and chained through permit->certificate for movement records.
  - Validation pipeline follows the scaffold's priority order: auth headers -> role -> body schema (incl. `inspection_date <= clock`, `test_date <= inspection_date`, window inversions, enum ranges) -> existence -> ownership -> state -> safety (vet current, disease hold, test qualifying, outbreak restriction) -> matrix/linkage -> temporal -> constraint -> OCC.
  - All state machines: Certificate (incl. system-driven auto-reject on INFECTED and ENTRY_BLOCKED with `pre_block_status` save/restore), MovementPermit (REQUESTED/ISSUED/SUSPENDED/VOIDED), MovementRecord, OutbreakZone (re-escalation loop), QuarantineOrder, TestRecord, Veterinarian, TransmissionAudit, Premises accreditation.
  - Calculations: `cvi_issuance_fee` (provisional at submit, final at issue, with MONITORED surcharge and 20000-cent cap); `movement_fee_reconciliation` with `Decimal` ROUND_HALF_UP per line item before summation (pinned order); `permit_headroom` committed vs projected; `certificate_validity_window` (30 days, strictly-greater lapse); whole-day age floors for test/vaccination windows.
  - OCC: `expected_permit_version` -> `ERR_STALE_PERMIT_VERSION` (412); `expected_requirement_version` -> `ERR_STALE_REQUIREMENT_VERSION` (412); checked after constraint validation per the priority table.
  - Cascades implemented atomically: POSITIVE test -> premises INFECTED + auto `QuarantineOrder` (`reason=AUTO_POSITIVE_TEST:<id>`, `issued_by_user_id="system"`, 30-day window) + DRAFT/PENDING_REVIEW cert rejection; zone escalate -> premises QUARANTINE_HOLD -> certs ENTRY_BLOCKED -> permits SUSPENDED; zone resolve (from CONTAINED) restores the chain in reverse; certificate void -> permits VOIDED + movement records CANCELLED; quarantine lift/expire re-evaluates premises; `current_head_count` derived from IN_TRANSIT/DELIVERED records so IN_TRANSIT cancellation automatically restores inventory.
  - Numbering: `CVI-<origin_state>-<seq:06d>` and `EP-<dest_state>-<seq:06d>` from two global monotonic sequences.
  - `payload_digest` is a lowercase 64-hex SHA-256 of a canonical transmitted payload string.
  - No entity seeding at startup; store starts empty each boot.

**Smoke verification:** 17 of 18 end-to-end scenarios passed against a live server (auth errors, RBAC, defaults, full cert->permit->movement lifecycle, ownership, vet-not-found, body validation, test-not-qualifying, POSITIVE cascade, zone escalate/contain/resolve cascade, quarantine segregation-of-duties, OCC on both guarded endpoints, lazy LAPSED after clock advance, pagination). The single "failure" was a bug in my throwaway test script (it reused a stale clock after the lapse test moved time forward), not in the implementation — the 422 returned was the correct `ERR_PERMIT_WINDOW_OUTSIDE_CVI_VALIDITY` for the inputs given.

## Step 5: Generate Unit Tests — 2026-08-14T00:16:27.631Z

(Launched concurrently with Step 6 in a single orchestrator message; finished second.)

Generation complete. All audits pass.

## What was generated

**`test_helpers/`** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1570_livestock_health_certificate_interstate/test_helpers/`):
- `types.py` — 10 entity TypedDicts + 15 status/role enums; all entities carry the full common set (`id`, `created_at`, `updated_at`, `version`) per PRD §2.6
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (37 methods incl. the `/_clock/set_current_utc` test-driving endpoint)
- `api_errors.py` — full 51-entry `ApiErrorId` enum + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity validators plus CVI/permit-number/SHA-256-digest format checks
- `factories.py`, `constants.py` (fee/headroom/validity constants + expected-value calculators), `test_users.py` (`TEST_USERS` + mandatory `make_vet_headers(id)` builder for the entity-backed `AccreditedVet` role)
- `fixtures.py` — composite lifecycle builders: `setup_standard_scenario`, `create_submitted_certificate`, `create_issued_certificate`, `setup_issued_certificate_with_permit`, `create_and_escalate_zone`, `transmit_and_acknowledge`, all threaded with per-instance vet identity
- `__init__.py` barrel

**`test_suite/`** (9 test files + `conftest.py`): `test_01_reference_data.py` (13), `test_02_certificate_lifecycle.py` (15), `test_03_certificate_submit_battery.py` (17), `test_04_permits_and_movements.py` (25), `test_05_outbreak_and_quarantine.py` (18), `test_06_fees_and_reconciliation.py` (5), `test_07_transmission_audit.py` (1), `test_08_security_and_concurrency.py` (10), `test_09_listing_and_traceback.py` (2).

## Audit results
- **Coverage**: all 18 difficulty instances have exactly ≥2 tests; all 70 non-stub corner instances have ≥1 test; all 21 `excluded_because:` stubs' cross-references resolve and were not translated; zero orphan tags; every test carries exactly one `Design:` line copied verbatim from the yaml `name:`.
- **PRD citations**: automated sweep — every quoted sentence in every docstring matches PRD.md verbatim (0 failures after fixing trailing-punctuation and elision issues, including a real typo caught by the sweep: `ERR_CERTIFICATE_NOT_TRANSMITTED` → PRD's actual `ERR_CERTIFICATE_NOT_TRANSMITTABLE`).
- **Collection**: 106 tests collect cleanly with the framework on PYTHONPATH; no `skip`/`skipif`/`xfail` markers; no scaffold references in comments.

## Judgment calls (PRD-first filter)
- Dropped the recipe's `version == 1` assertion in `premises_creation_defaults_applied` — PRD §2.6 says version "starts at its initial value" without naming the value, so it isn't uniquely derivable; version increments are instead asserted relationally (`v+1`) in the two OCC tests.
- Omitted the backward clock move (2026-08-01 → 2026-07-15) in `veterinarian_is_credential_current_computed` — PRD only licenses advancing the clock ("once advanced, the clock stays where it was set"); the computed flags are asserted from the create responses at the startup default clock.
- Exact minted identifiers (`CVI-CA-000001`, `EP-KS-000001`) are asserted on first issuance, matching PRD §2.10's canonical examples.

## Step 7: Run Tests and Iterate — 2026-08-14T00:30:32.113Z

All 8 rounds pass 106/106. Exit clean. (Orchestrator independently re-read all 8 results files: 106/106, 0 failed, 0 errors, ×8.)

## Summary

- **Iterations run**: 2 (first sweep identified 14 deterministic failures across 3 buckets; fixes applied; second sweep confirmed 106/106 × 8 rounds).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `test_suite/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1570_livestock_health_certificate_interstate/test_suite/test_02_certificate_lifecycle.py`
    - `test_certificate_submit_twice_rejected`, `test_certificate_revise_requires_rejected` (cert_b), `test_certificate_revision_cycle_returns_to_draft`, `test_certificate_revision_cycle_resubmits_with_recomputed_fee` — added missing `test_record_id=scenario["test"]["id"]` and `vaccination_date=DEFAULTS["VACCINATION_DATE"]` to draft-certificate creation, because the default scenario installs a NON-NONE matrix row that requires both per PRD §3.4/§160. Added `DEFAULTS` to imports.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1570_livestock_health_certificate_interstate/test_suite/test_04_permits_and_movements.py`
    - `test_depart_blocked_when_inventory_consumed_by_other_certificate` — same fixture fix for cert_a and cert_b; added `DEFAULTS` to imports.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1570_livestock_health_certificate_interstate/test_suite/test_05_outbreak_and_quarantine.py`
    - `TestQuarantineSpacing._setup_lifted_order` — pinned the logical clock to `2026-07-01T00:00:00Z` (inside q1's active window) before lifting, so the lazy `EXPIRED` materialization per PRD §2.4 doesn't pre-empt the lift with `ERR_QUARANTINE_NOT_ACTIVE`. The tests then create q2 in the future relative to that clock; q2 is born `ACTIVE` as PRD requires.

- **Fixes applied to `implementation/`**:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1570_livestock_health_certificate_interstate/workspace/implementation/app.py`
    - Added `_ts_instant()` helper emitting ISO-8601 UTC at second precision. Serializer now uses `_ts_instant` for all entity datetime fields except `created_at`/`updated_at` (which keep the 3-fractional-digit `_ts` per PRD §104); `set_clock` response now uses `_ts_instant` so `current_utc` echoes the supplied `to_iso8601` (per PRD §82's `2026-08-01T00:00:00Z` clock format). The transmission-audit canonical payload still uses `_ts` (its byte format is implementation-defined per PRD §130).

## Step 8: Finalize PRD — 2026-08-14T00:33:52.159Z

(Step 8 ran because Step 7 made fixes — 5 test_suite fixes + 1 implementation fix, 0 deletions.)

## Summary

**File created:** `/home/ubuntu/github/CodingPRD/tasks/task_1570_livestock_health_certificate_interstate/workspace/PRD_FINALIZED.md`

**Line counts & delta:**
- `PRD.md`: 336 lines
- `PRD_FINALIZED.md`: 338 lines (+2 lines, +0.60%)

**Changes (one bullet each):**
- **§2.4** — revise — added sentence pinning the `current_utc` response of `POST /_clock/set_current_utc` to ISO 8601 UTC at second precision (`YYYY-MM-DDTHH:MM:SSZ`), echoing the supplied `to_iso8601` with fractional seconds dropped — `implementation/app.py:717` (and `_ts_instant` at `app.py:178-186`).
- **§2.6** — insert — added paragraph pinning the wire format of every entity datetime field other than `created_at`/`updated_at` (e.g. `inspection_date`, `vaccination_date`, `issued_at`, `valid_until`, `accreditation_expires_at`, `effective_from`, `effective_until`, `test_date`, `planned_ship_date`, `departed_at`, `arrived_at`, `start_at`, `end_at`, `acknowledged_at`) to ISO 8601 UTC at second precision, regardless of fractional digits on input — `implementation/app.py:554-567` (serializer), `_ts_instant` at `app.py:178-186`, and `DT_FIELDS` at `app.py:540-551`.

**No PRD edits were made for the test_suite-only fixes** (certificate draft fixtures adding `test_record_id`/`vaccination_date`, and the quarantine-spacing clock pin) — these are pure fixture bugs where PRD already pinned the behavior (PRD §3.3/§3.4 already require `test_record_id` when the matrix row's `test_type` is not `NONE` and `vaccination_date` when vaccination is required; PRD §2.4/§3.7 already pin lazy `EXPIRED` materialization and `ERR_QUARANTINE_NOT_ACTIVE`).

**Per-edit pre-edit search log:**

*Edit 1 — §2.4 `current_utc` wire format:*
- (a) Subject: response serialization format of the `set_clock` endpoint's `current_utc` field.
- (b) Impl paths enumerated/read: `set_clock` route at `app.py:711-717` (the only endpoint producing `current_utc`); `_ts_instant` helper at `app.py:178-186`; `_ts` helper at `app.py:173-175` for contrast; test assertion `test_08_security_and_concurrency.py:488` (`current_utc == "2026-08-10T00:00:00Z"`); all `set_clock` callers in `test_helpers/api_client.py:7-9` and `test_helpers/fixtures.py:85-87`; grep for other `current_utc` producers (none).
- (c) Wording chosen is scoped narrowly to the `current_utc` field only; explicitly says fractional seconds are dropped (matching `strftime("%Y-%m-%dT%H:%M:%SZ")` truncation of `to_dt`). Does not affect the request-side `to_iso8601` acceptance (which still permits fractional input per `datetime.fromisoformat` at `app.py:351`).

*Edit 2 — §2.6 entity datetime serialization:*
- (a) Subject: response serialization format of every entity datetime field other than `created_at`/`updated_at`.
- (b) Impl paths enumerated/read: `serialize()` at `app.py:554-567` (single funnel for all entity responses); `serialize_premises`/`serialize_veterinarian`/`serialize_permit` wrappers at `app.py:570-589`; the complete `DT_FIELDS` map at `app.py:540-551` enumerating every datetime-bearing field per entity kind; every response site in the app (grep of `return success(serialize…)` at lines 750, 758, 774, 798, 809, 866, 908, 928, 1001, 1020, 1030, 1104, 1112, 1139, 1206, 1232, 1247, 1263, 1295, 1327, 1359, 1366, 1376, 1403, 1440, 1516, 1547, 1563, 1588, 1597, 1649, 1733, 1744, 1758, plus the quarantine/zone/transmission sites I confirmed also route through `serialize`); contrasted against the transmission-payload canonical byte format at `app.py:1308-1314` which deliberately uses `_ts` (3-fraction) but is implementation-defined per PRD §2.10 (PRD only pins the SHA-256 hex digest, not the canonical byte layout), so no wording about it was added; contrasted against `api_request_timestamp` at `app.py:192, 209, 222, 235` which remains 3-fraction per PRD §2.2 — untouched.
- (c) Wording says "every other datetime-valued field an entity carries" with a "for example" non-exhaustive list, so the rule applies uniformly across all enumerated paths (including any I may have missed). Explicitly excludes `created_at`/`updated_at` by saying "every other" relative to the sentence immediately above. The phrase "regardless of any fractional digits supplied on input" is justified by the parse-then-strftime pipeline (`req_dt` at `app.py:344-356` keeps microseconds; `_ts_instant` truncates via `strftime`).

## Step 9: Complete PRD — 2026-08-14T00:46:48.227Z

All pins are in place. The work is complete.

## Summary

**Files** — Source: `/home/ubuntu/github/CodingPRD/tasks/task_1570_livestock_health_certificate_interstate/workspace/PRD_FINALIZED.md` (338 lines, 54,605 chars) → Produced: `/home/ubuntu/github/CodingPRD/tasks/task_1570_livestock_health_certificate_interstate/workspace/PRD_COMPLETED.md` (342 lines, 58,207 chars). Delta: +4 lines, +3,602 chars.

**Counts** — Ambiguity-pins: 14. Mismatch-revisions: 10.

**Changes (one per bullet):**

- §2.1 — insert — ambiguity — unrecognized role strings (outside the five) are rejected with `ERR_FORBIDDEN` — implementation/app.py:256-260
- §2.1 — revise — mismatch — the `ERR_VETERINARIAN_NOT_FOUND` identity resolution applies only to AccreditedVet *write* requests; shared read endpoints do not resolve the veterinarian — implementation/app.py:753-758 vs 697-699
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + 24 lowercase hex characters — implementation/app.py:169-170
- §2.2 — revise — ambiguity — `api_request_timestamp` is taken from the logical clock, not wall-clock time — implementation/app.py:189-193
- §2.2 — insert — ambiguity — undefined paths answer 404 and unsupported methods 405, both in the error envelope with `error_id` `ERR_VALIDATION` — implementation/app.py:217-240
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_VALIDATION` (400); sort ties in `created_at` break by `id` — implementation/app.py:598-619
- §2.4 — revise — ambiguity — clock-set answers HTTP 200 and adopts the supplied instant verbatim, even if earlier than the current reading — implementation/app.py:711-717
- §2.5 layer 3 — insert — ambiguity — required string fields must be non-empty — implementation/app.py:279-285
- §2.5 layers 7(c)/8 — revise — mismatch — the `ERR_TEST_NOT_QUALIFYING` gate is evaluated inside layer 8 at submission, after matrix existence and species checks; layer 8 gains the test-record-presence sub-step — implementation/app.py:1162-1183
- §2.6 — revise — ambiguity — `version` starts at 1 on creation — implementation/app.py:394-401
- §2.6 — insert — ambiguity — input datetime strings may carry any ISO 8601 offset (or none = UTC) and are normalized to UTC — implementation/app.py:344-356
- §2.8 — insert — mismatch — on both OCC-guarded PATCH operations, path-id existence is resolved before field-level body validation (404 beats `ERR_VALIDATION`) — implementation/app.py:870-895, 1407-1417
- §3.1 — revise — mismatch — `accreditation_number` uniqueness is not enforced by the server (PRD previously claimed unique) — implementation/app.py:782-798
- §3.1 — insert — ambiguity — an explicit null `disease_status` at premises registration is treated as omitted (→ `MONITORED`) — implementation/app.py:734-738
- §3.2 — revise — ambiguity — auto-quarantine `disease_code` is the disease code bearing the same name as the test type — implementation/app.py:82-87, 937-938, 962
- §3.3 — revise — mismatch — drafting does not consult the matrix; `test_record_id`/`vaccination_date` requiredness is enforced only at submission — implementation/app.py:1057-1104
- §3.3 — insert — ambiguity — creation resolves premises first, then test record, then evaluates the `test_date`-vs-`inspection_date` rule — implementation/app.py:1075-1080
- §3.4 — revise — mismatch — submission battery order corrected to: credential, disease hold, matrix existence, species, test presence/result, linkage, temporal windows, inventory — implementation/app.py:1155-1201
- §3.4 — insert — ambiguity — a missing `test_record_id` at submission against a non-`NONE` row fails as `ERR_TEST_RECORD_MISMATCH` — implementation/app.py:1171-1173
- §3.4 — insert — ambiguity — the certificate list endpoint also materializes lazy `LAPSED` on every certificate before filtering — implementation/app.py:1124-1125
- §3.4 — insert — ambiguity — voiding an `ENTRY_BLOCKED` certificate clears `pre_block_status` to null — implementation/app.py:1277
- §3.5 — revise — mismatch — permit *request* runs no ownership check and no certificate-state check (any registered vet, any existing certificate; state bites at issuance, ownership at scheduling) — implementation/app.py:1335-1359
- §3.5 — revise — mismatch — permit issuance evaluates window-containment (`ERR_PERMIT_WINDOW_OUTSIDE_CVI_VALIDITY`) before the allocation floor (`ERR_ALLOCATION_BELOW_CERTIFICATE_HEADCOUNT`) — implementation/app.py:1394-1397
- §3.5 — insert — ambiguity — adjustment rules: supplied `allocated_head_count` ≥ 1, supplied `valid_until` not before `valid_from`, and no re-run of certificate-containment — implementation/app.py:1412-1428
- §3.5 — revise — mismatch — departure check order corrected to: disease hold, outbreak zone, window, inventory — implementation/app.py:1533-1542
- §3.7 — insert — ambiguity — quarantine-order `disease_code` must be one of the seven §3.6 codes — implementation/app.py:1772
- §3.8 — insert — ambiguity — canonical payload for `payload_digest` pinned as pipe-delimited `id|cvi_number|destination_state_code|species_code|head_count|issued_at|valid_until|channel` with empty null segments and 3-fractional-digit timestamps — implementation/app.py:1308-1314
- §3.8 — revise — ambiguity — acknowledgement bubbles the certificate to `TRANSMITTED` only when it stands `ISSUED` after lazy `LAPSED` materialization; all other states untouched — implementation/app.py:1880-1885

All other PRD passages were verified against the implementation (fee formulas, movement rates and rounding order, whole-day age rules, cascades for infection/void/escalate/resolve/lift, quarantine spacing rules, lazy materialization triggers, state-machine transition errors, role-per-endpoint table, and the error catalogue) and already pinned the implemented behavior uniquely, so they were left unchanged.
