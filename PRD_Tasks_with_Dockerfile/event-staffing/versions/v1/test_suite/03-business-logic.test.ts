import {
    apiClient,
    buildUserHeaders,
    handleApiResponse,
    validateErrorEnvelope, assertShift, assertAssignment,
    createContractPayload,
    createEventPayload,
    createShiftPayload,
    createStaffProfilePayload,
    createAssignmentPayload,
    createConflictPairingPayload, StaffingContract,
    Event,
    Shift,
    StaffProfile,
    Assignment, ShiftStatus,
    AssignmentStatus,
    UserRole,
    CertificationType,
    ApiErrorId,
    createAndActivateContract
} from '../../../test-helpers';

describe('Phase 3: Business Logic Unit Tests', () => {
    const coordinatorHeaders = buildUserHeaders('coordinator-1', UserRole.StaffingCoordinator);
    const staffMemberHeaders = buildUserHeaders('staff-1', UserRole.StaffMember);
    const accountManagerHeaders = buildUserHeaders('manager-1', UserRole.AccountManager);

    describe('Rule: create-shift-rule', () => {
        describe('P3-CREATE-SHIFT-01.1: Happy path - create shift under active contract', () => {
            it('should successfully create a shift with valid data', async () => {
                const contract = await createAndActivateContract();
                const eventRes = await apiClient.createEvent(
                    contract.id,
                    createEventPayload({ name: 'Test Event' }),
                    coordinatorHeaders
                );
                const event = handleApiResponse<Event>(eventRes, 201);

                const shiftPayload = createShiftPayload({
                    role_name: 'Server',
                    certification_needed: CertificationType.NONE,
                    start_time: 1700000000,
                    end_time: 1700018000,
                });
                const res = await apiClient.createShift(contract.id, event.id, shiftPayload, coordinatorHeaders);
                const shift = handleApiResponse<Shift>(res, 201);

                assertShift(shift);
                expect(shift.role_name).toBe('Server');
                expect(shift.certification_needed).toBe(CertificationType.NONE);
                expect(shift.start_time).toBe(1700000000);
                expect(shift.end_time).toBe(1700018000);
                expect(shift.status).toBe(ShiftStatus.OPEN);

                const getRes = await apiClient.getShift(contract.id, event.id, shift.id, coordinatorHeaders);
                const retrievedShift = handleApiResponse<Shift>(getRes, 200);
                expect(retrievedShift.id).toBe(shift.id);
                expect(retrievedShift.role_name).toBe('Server');
            });
        });

        describe('P3-CREATE-SHIFT-01.4: Invalid shift times', () => {
            it('should reject shift creation if end_time is not after start_time', async () => {
                const contract = await createAndActivateContract();
                const eventRes = await apiClient.createEvent(
                    contract.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                const event = handleApiResponse<Event>(eventRes, 201);

                const shiftPayload = createShiftPayload({
                    role_name: 'Server',
                    start_time: 1700000000,
                    end_time: 1700000000,
                });
                const res = await apiClient.createShift(contract.id, event.id, shiftPayload, coordinatorHeaders);

                validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INVALID_SHIFT_TIMES });
            });
        });
    });

    describe('Rule: create-assignment-nexus-rule', () => {
        describe('P3-ASSIGN-NEXUS-01.1: Happy path - non-overtime assignment', () => {
            it('should create assignment with correct state and ledger effects', async () => {
                const contract = await createAndActivateContract(1000.00);
                const eventRes = await apiClient.createEvent(
                    contract.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                const event = handleApiResponse<Event>(eventRes, 201);

                const shiftRes = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({
                        start_time: 1700000000,
                        end_time: 1700014400,
                    }),
                    coordinatorHeaders
                );
                const shift = handleApiResponse<Shift>(shiftRes, 201);

                const staffRes = await apiClient.createStaffProfile(
                    contract.id,
                    createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }),
                    coordinatorHeaders
                );
                const staff = handleApiResponse<StaffProfile>(staffRes, 201);

                const assignmentRes = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift.id, staff.id),
                    accountManagerHeaders
                );
                const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

                assertAssignment(assignment);
                expect(assignment.status).toBe(AssignmentStatus.PROPOSED);
                expect(assignment.is_overtime_eligible).toBe(false);
                expect(assignment.provisional_cost).toBe(80.00);

                const shiftCheckRes = await apiClient.getShift(contract.id, event.id, shift.id, coordinatorHeaders);
                const updatedShift = handleApiResponse<Shift>(shiftCheckRes, 200);
                expect(updatedShift.status).toBe(ShiftStatus.PENDING_CONFIRMATION);

                const contractCheckRes = await apiClient.getContract(contract.id, coordinatorHeaders);
                const updatedContract = handleApiResponse<StaffingContract>(contractCheckRes, 200);
                expect(updatedContract.budget_balance).toBe(920.00);
                expect(updatedContract.compliance_risk_score).toBe(0);
            });
        });

        describe('P3-ASSIGN-NEXUS-01.2: Overtime assignment - insufficient budget', () => {
            it('should reject assignment when provisional cost exceeds budget', async () => {
                const contract = await createAndActivateContract(1000.00);
                const eventRes = await apiClient.createEvent(
                    contract.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                const event = handleApiResponse<Event>(eventRes, 201);

                const staffRes = await apiClient.createStaffProfile(
                    contract.id,
                    createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }),
                    coordinatorHeaders
                );
                const staff = handleApiResponse<StaffProfile>(staffRes, 201);

                for (let i = 0; i < 4; i++) {
                    const shiftRes = await apiClient.createShift(
                        contract.id,
                        event.id,
                        createShiftPayload({
                            start_time: 1700000000 + (i * 86400),
                            end_time: 1700000000 + (i * 86400) + 36000,
                        }),
                        coordinatorHeaders
                    );
                    const shift = handleApiResponse<Shift>(shiftRes, 201);

                    const assignmentRes = await apiClient.createAssignment(
                        contract.id,
                        createAssignmentPayload(shift.id, staff.id),
                        accountManagerHeaders
                    );
                    const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

                    await apiClient.acceptAssignment(contract.id, assignment.id, staffMemberHeaders);
                    await apiClient.confirmAssignment(contract.id, assignment.id, coordinatorHeaders);
                }

                const shift5Res = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({
                        start_time: 1700000000 + (4 * 86400),
                        end_time: 1700000000 + (4 * 86400) + 36000,
                    }),
                    coordinatorHeaders
                );
                const shift5 = handleApiResponse<Shift>(shift5Res, 201);

                const res = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift5.id, staff.id),
                    accountManagerHeaders
                );

                validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
            });
        });

        describe('P3-ASSIGN-NEXUS-01.2.1: Overtime assignment - sufficient budget', () => {
            it('should flag overtime and increment compliance risk', async () => {
                const contract = await createAndActivateContract(2000.00);
                const eventRes = await apiClient.createEvent(
                    contract.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                const event = handleApiResponse<Event>(eventRes, 201);

                const staffRes = await apiClient.createStaffProfile(
                    contract.id,
                    createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }),
                    coordinatorHeaders
                );
                const staff = handleApiResponse<StaffProfile>(staffRes, 201);

                for (let i = 0; i < 4; i++) {
                    const shiftRes = await apiClient.createShift(
                        contract.id,
                        event.id,
                        createShiftPayload({
                            start_time: 1700000000 + (i * 86400),
                            end_time: 1700000000 + (i * 86400) + 36000,
                        }),
                        coordinatorHeaders
                    );
                    const shift = handleApiResponse<Shift>(shiftRes, 201);

                    const assignmentRes = await apiClient.createAssignment(
                        contract.id,
                        createAssignmentPayload(shift.id, staff.id),
                        accountManagerHeaders
                    );
                    const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

                    await apiClient.acceptAssignment(contract.id, assignment.id, staffMemberHeaders);
                    await apiClient.confirmAssignment(contract.id, assignment.id, coordinatorHeaders);
                }

                const shift5Res = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({
                        start_time: 1700000000 + (4 * 86400),
                        end_time: 1700000000 + (4 * 86400) + 36000,
                    }),
                    coordinatorHeaders
                );
                const shift5 = handleApiResponse<Shift>(shift5Res, 201);

                const assignmentRes = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift5.id, staff.id),
                    accountManagerHeaders
                );
                const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

                expect(assignment.is_overtime_eligible).toBe(true);
                expect(assignment.provisional_cost).toBe(300.00);

                const contractCheckRes = await apiClient.getContract(contract.id, coordinatorHeaders);
                const updatedContract = handleApiResponse<StaffingContract>(contractCheckRes, 200);
                expect(updatedContract.compliance_risk_score).toBe(5);
            });
        });

        describe('P3-ASSIGN-NEXUS-01.3: Contract not active', () => {
            it('should reject assignment if contract is in PLANNING state', async () => {
                const contractRes = await apiClient.createContract(createContractPayload(), coordinatorHeaders);
                const contract = handleApiResponse<StaffingContract>(contractRes, 201);

                const activeContract = await createAndActivateContract();
                const eventRes = await apiClient.createEvent(
                    activeContract.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                const event = handleApiResponse<Event>(eventRes, 201);

                const shiftRes = await apiClient.createShift(
                    activeContract.id,
                    event.id,
                    createShiftPayload(),
                    coordinatorHeaders
                );
                const shift = handleApiResponse<Shift>(shiftRes, 201);

                const staffRes = await apiClient.createStaffProfile(
                    activeContract.id,
                    createStaffProfilePayload(),
                    coordinatorHeaders
                );
                const staff = handleApiResponse<StaffProfile>(staffRes, 201);

                const res = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift.id, staff.id),
                    accountManagerHeaders
                );

                validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_ACTIVE });
            });
        });

        describe('P3-ASSIGN-NEXUS-01.4: Shift belongs to different contract', () => {
            it('should reject assignment if shift belongs to different contract', async () => {
                const contractA = await createAndActivateContract();
                const contractB = await createAndActivateContract();

                const eventBRes = await apiClient.createEvent(
                    contractB.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                const eventB = handleApiResponse<Event>(eventBRes, 201);

                const shiftBRes = await apiClient.createShift(
                    contractB.id,
                    eventB.id,
                    createShiftPayload(),
                    coordinatorHeaders
                );
                const shiftB = handleApiResponse<Shift>(shiftBRes, 201);

                const staffARes = await apiClient.createStaffProfile(
                    contractA.id,
                    createStaffProfilePayload(),
                    coordinatorHeaders
                );
                const staffA = handleApiResponse<StaffProfile>(staffARes, 201);

                const res = await apiClient.createAssignment(
                    contractA.id,
                    createAssignmentPayload(shiftB.id, staffA.id),
                    accountManagerHeaders
                );

                validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SHIFT_NOT_FOUND });
            });
        });

        describe('P3-ASSIGN-NEXUS-01.5: Shift not OPEN', () => {
            it('should reject assignment if shift is not OPEN', async () => {
                const contract = await createAndActivateContract();
                const eventRes = await apiClient.createEvent(
                    contract.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                const event = handleApiResponse<Event>(eventRes, 201);

                const shiftRes = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload(),
                    coordinatorHeaders
                );
                const shift = handleApiResponse<Shift>(shiftRes, 201);

                const staff1Res = await apiClient.createStaffProfile(
                    contract.id,
                    createStaffProfilePayload({ first_name: 'Staff1' }),
                    coordinatorHeaders
                );
                const staff1 = handleApiResponse<StaffProfile>(staff1Res, 201);

                const staff2Res = await apiClient.createStaffProfile(
                    contract.id,
                    createStaffProfilePayload({ first_name: 'Staff2' }),
                    coordinatorHeaders
                );
                const staff2 = handleApiResponse<StaffProfile>(staff2Res, 201);

                await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift.id, staff1.id),
                    accountManagerHeaders
                );

                const res = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift.id, staff2.id),
                    accountManagerHeaders
                );

                validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SHIFT_NOT_OPEN });
            });
        });

        describe('P3-ASSIGN-NEXUS-01.6: Staff belongs to different contract', () => {
            it('should reject assignment if staff belongs to different contract', async () => {
                const contractA = await createAndActivateContract();
                const contractB = await createAndActivateContract();

                const eventARes = await apiClient.createEvent(
                    contractA.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                const eventA = handleApiResponse<Event>(eventARes, 201);

                const shiftARes = await apiClient.createShift(
                    contractA.id,
                    eventA.id,
                    createShiftPayload(),
                    coordinatorHeaders
                );
                const shiftA = handleApiResponse<Shift>(shiftARes, 201);

                const staffBRes = await apiClient.createStaffProfile(
                    contractB.id,
                    createStaffProfilePayload(),
                    coordinatorHeaders
                );
                const staffB = handleApiResponse<StaffProfile>(staffBRes, 201);

                const res = await apiClient.createAssignment(
                    contractA.id,
                    createAssignmentPayload(shiftA.id, staffB.id),
                    accountManagerHeaders
                );

                validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_STAFF_NOT_FOUND });
            });
        });

        describe('P3-ASSIGN-NEXUS-01.7: Missing required certification', () => {
            it('should reject assignment if staff lacks required certification', async () => {
                const contract = await createAndActivateContract();
                const eventRes = await apiClient.createEvent(
                    contract.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                const event = handleApiResponse<Event>(eventRes, 201);

                const shiftRes = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({
                        certification_needed: CertificationType.ALCOHOL_SERVICE_LICENSE,
                    }),
                    coordinatorHeaders
                );
                const shift = handleApiResponse<Shift>(shiftRes, 201);

                const staffRes = await apiClient.createStaffProfile(
                    contract.id,
                    createStaffProfilePayload(),
                    coordinatorHeaders
                );
                const staff = handleApiResponse<StaffProfile>(staffRes, 201);

                const res = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift.id, staff.id),
                    accountManagerHeaders
                );

                validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISSING });
            });
        });

        describe('P3-ASSIGN-NEXUS-01.7.1: Positive certification match', () => {
            it('should create assignment if staff has required certification', async () => {
                const contract = await createAndActivateContract();
                const eventRes = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders);
                const event = handleApiResponse<Event>(eventRes, 201);

                const shiftRes = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({
                        certification_needed: CertificationType.FOOD_HANDLER_PERMIT,
                    }),
                    coordinatorHeaders
                );
                const shift = handleApiResponse<Shift>(shiftRes, 201);

                const staffPayload = createStaffProfilePayload();
                const staffRes = await apiClient.createStaffProfile(contract.id, staffPayload, coordinatorHeaders);
                const staff = handleApiResponse<StaffProfile>(staffRes, 201);

                await apiClient.addCertification(contract.id, staff.id, {
                    name: CertificationType.FOOD_HANDLER_PERMIT,
                    issued_date: '2024-01-01',
                    expiry_date: '2030-01-01',
                }, coordinatorHeaders);

                const res = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift.id, staff.id),
                    accountManagerHeaders
                );
                const assignment = handleApiResponse<Assignment>(res, 201);

                assertAssignment(assignment);
                expect(assignment.shift_id).toBe(shift.id);
                expect(assignment.staff_profile_id).toBe(staff.id);
            });
        });

        describe('P3-ASSIGN-NEXUS-01.8: Rest period violation', () => {
            it('should reject assignment if rest period is violated with a shift in another event', async () => {
                const contract = await createAndActivateContract();
                const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));
                const staffMemberHeaders = buildUserHeaders(staff.id, UserRole.StaffMember);
                const accountManagerHeaders = buildUserHeaders('manager-1', UserRole.AccountManager);

                const event1 = await apiClient.createEvent(contract.id, createEventPayload({ name: 'Event One' }), coordinatorHeaders).then(r => handleApiResponse<Event>(r, 201));
                const shift1 = await apiClient.createShift(contract.id, event1.id, createShiftPayload({ start_time: 1700000000, end_time: 1700028800 }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));
                const assign1 = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift1.id, staff.id), accountManagerHeaders).then(r => handleApiResponse<Assignment>(r, 201));
                await apiClient.acceptAssignment(contract.id, assign1.id, staffMemberHeaders);
                await apiClient.confirmAssignment(contract.id, assign1.id, coordinatorHeaders);

                const event2 = await apiClient.createEvent(contract.id, createEventPayload({ name: 'Event Two' }), coordinatorHeaders).then(r => handleApiResponse<Event>(r, 201));
                const shift2 = await apiClient.createShift(contract.id, event2.id, createShiftPayload({ start_time: 1700057599, end_time: 1700061199 }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));

                const res = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift2.id, staff.id), accountManagerHeaders);

                validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_REST_PERIOD_VIOLATION });
            });
        });

        describe('P3-ASSIGN-NEXUS-01.8.1: Rest period check includes PROPOSED assignments', () => {
            it('should reject assignment if rest period conflicts with a PROPOSED assignment', async () => {
                const contract = await createAndActivateContract();
                const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders).then(r => handleApiResponse<Event>(r, 201));
                const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));

                const shift1 = await apiClient.createShift(contract.id, event.id, createShiftPayload({
                    start_time: 1700000000,
                    end_time: 1700028800,
                }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));
                await apiClient.createAssignment(contract.id, createAssignmentPayload(shift1.id, staff.id), accountManagerHeaders);

                const shift2 = await apiClient.createShift(contract.id, event.id, createShiftPayload({
                    start_time: 1700057599,
                    end_time: 1700061199,
                }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));

                const res = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift2.id, staff.id), accountManagerHeaders);

                validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_REST_PERIOD_VIOLATION });
            });
        });

        describe('P3-ASSIGN-NEXUS-01.9: Interpersonal conflict', () => {
            it('should reject assignment if staff has conflict with someone in same event', async () => {
                const contract = await createAndActivateContract();
                const eventRes = await apiClient.createEvent(
                    contract.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                const event = handleApiResponse<Event>(eventRes, 201);

                const janeRes = await apiClient.createStaffProfile(
                    contract.id,
                    createStaffProfilePayload({ first_name: 'Jane' }),
                    coordinatorHeaders
                );
                const jane = handleApiResponse<StaffProfile>(janeRes, 201);

                const johnRes = await apiClient.createStaffProfile(
                    contract.id,
                    createStaffProfilePayload({ first_name: 'John' }),
                    coordinatorHeaders
                );
                const john = handleApiResponse<StaffProfile>(johnRes, 201);

                await apiClient.createConflictPairing(
                    contract.id,
                    createConflictPairingPayload(jane.id, john.id),
                    coordinatorHeaders
                );

                const shiftARes = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({ role_name: 'Shift A' }),
                    coordinatorHeaders
                );
                const shiftA = handleApiResponse<Shift>(shiftARes, 201);

                const assignmentARes = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shiftA.id, jane.id),
                    accountManagerHeaders
                );
                const assignmentA = handleApiResponse<Assignment>(assignmentARes, 201);
                await apiClient.acceptAssignment(contract.id, assignmentA.id, staffMemberHeaders);
                await apiClient.confirmAssignment(contract.id, assignmentA.id, coordinatorHeaders);

                const shiftBRes = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({ role_name: 'Shift B' }),
                    coordinatorHeaders
                );
                const shiftB = handleApiResponse<Shift>(shiftBRes, 201);

                const res = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shiftB.id, john.id),
                    accountManagerHeaders
                );

                validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INTERPERSONAL_CONFLICT });
            });
        });

        describe('P3-ASSIGN-NEXUS-01.10: Insufficient budget', () => {
            it('should reject assignment if cost exceeds remaining budget', async () => {
                const contract = await createAndActivateContract(100.00);
                const eventRes = await apiClient.createEvent(
                    contract.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                const event = handleApiResponse<Event>(eventRes, 201);

                const shiftRes = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({
                        start_time: 1700000000,
                        end_time: 1700021600,
                    }),
                    coordinatorHeaders
                );
                const shift = handleApiResponse<Shift>(shiftRes, 201);

                const staffRes = await apiClient.createStaffProfile(
                    contract.id,
                    createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }),
                    coordinatorHeaders
                );
                const staff = handleApiResponse<StaffProfile>(staffRes, 201);

                const res = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift.id, staff.id),
                    accountManagerHeaders
                );

                validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
            });
        });

        describe('P3-ASSIGN-NEXUS-01.11: Risk threshold exceeded', () => {
            it('should reject overtime assignment when risk score meets threshold without override', async () => {
                const contract = await createAndActivateContract(10000.00);
                const eventRes = await apiClient.createEvent(
                    contract.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                const event = handleApiResponse<Event>(eventRes, 201);

                const staffRes = await apiClient.createStaffProfile(
                    contract.id,
                    createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }),
                    coordinatorHeaders
                );
                const staff = handleApiResponse<StaffProfile>(staffRes, 201);

                for (let i = 0; i < 3; i++) {
                    const otherStaffRes = await apiClient.createStaffProfile(
                        contract.id,
                        createStaffProfilePayload({ first_name: `OTStaff${i}` }),
                        coordinatorHeaders
                    );
                    const otherStaff = handleApiResponse<StaffProfile>(otherStaffRes, 201);

                    const otShiftRes = await apiClient.createShift(
                        contract.id,
                        event.id,
                        createShiftPayload({
                            start_time: 1700000000 + (i * 150000),
                            end_time: 1700000000 + (i * 150000) + 147600,
                        }),
                        coordinatorHeaders
                    );
                    const otShift = handleApiResponse<Shift>(otShiftRes, 201);

                    const otAssignRes = await apiClient.createAssignment(
                        contract.id,
                        createAssignmentPayload(otShift.id, otherStaff.id),
                        accountManagerHeaders
                    );
                    const otAssign = handleApiResponse<Assignment>(otAssignRes, 201);
                    await apiClient.acceptAssignment(contract.id, otAssign.id, staffMemberHeaders);
                    await apiClient.confirmAssignment(contract.id, otAssign.id, coordinatorHeaders);
                }

                const shift40Res = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({
                        start_time: 1700000000,
                        end_time: 1700144000,
                    }),
                    coordinatorHeaders
                );
                const shift40 = handleApiResponse<Shift>(shift40Res, 201);

                const assign40Res = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift40.id, staff.id),
                    accountManagerHeaders
                );
                const assign40 = handleApiResponse<Assignment>(assign40Res, 201);
                await apiClient.acceptAssignment(contract.id, assign40.id, staffMemberHeaders);
                await apiClient.confirmAssignment(contract.id, assign40.id, coordinatorHeaders);

                const newShiftRes = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({
                        start_time: 1700200000,
                        end_time: 1700203600,
                    }),
                    coordinatorHeaders
                );
                const newShift = handleApiResponse<Shift>(newShiftRes, 201);

                const res = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(newShift.id, staff.id, { override_risk_check: false }),
                    accountManagerHeaders
                );

                validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_RISK_THRESHOLD_EXCEEDED });
            });
        });

        describe('P3-ASSIGN-NEXUS-01.12: Override when threshold breached', () => {
            it('should allow overtime assignment with override and apply both penalties', async () => {
                const contract = await createAndActivateContract(10000.00);
                const eventRes = await apiClient.createEvent(
                    contract.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                const event = handleApiResponse<Event>(eventRes, 201);

                for (let i = 0; i < 3; i++) {
                    const otherStaffRes = await apiClient.createStaffProfile(
                        contract.id,
                        createStaffProfilePayload({ first_name: `OTStaff${i}` }),
                        coordinatorHeaders
                    );
                    const otherStaff = handleApiResponse<StaffProfile>(otherStaffRes, 201);

                    const otShiftRes = await apiClient.createShift(
                        contract.id,
                        event.id,
                        createShiftPayload({
                            start_time: 1700000000 + (i * 150000),
                            end_time: 1700000000 + (i * 150000) + 147600,
                        }),
                        coordinatorHeaders
                    );
                    const otShift = handleApiResponse<Shift>(otShiftRes, 201);

                    const otAssignRes = await apiClient.createAssignment(
                        contract.id,
                        createAssignmentPayload(otShift.id, otherStaff.id),
                        accountManagerHeaders
                    );
                    const otAssign = handleApiResponse<Assignment>(otAssignRes, 201);
                    await apiClient.acceptAssignment(contract.id, otAssign.id, staffMemberHeaders);
                    await apiClient.confirmAssignment(contract.id, otAssign.id, coordinatorHeaders);
                }

                const contractStateRes = await apiClient.getContract(contract.id, coordinatorHeaders);
                const contractBefore = handleApiResponse<StaffingContract>(contractStateRes, 200);
                expect(contractBefore.compliance_risk_score).toBe(15);

                const staffRes = await apiClient.createStaffProfile(
                    contract.id,
                    createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }),
                    coordinatorHeaders
                );
                const staff = handleApiResponse<StaffProfile>(staffRes, 201);

                const shift40Res = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({
                        start_time: 1700500000,
                        end_time: 1700644000,
                    }),
                    coordinatorHeaders
                );
                const shift40 = handleApiResponse<Shift>(shift40Res, 201);

                const assign40Res = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift40.id, staff.id),
                    accountManagerHeaders
                );
                const assign40 = handleApiResponse<Assignment>(assign40Res, 201);
                await apiClient.acceptAssignment(contract.id, assign40.id, staffMemberHeaders);
                await apiClient.confirmAssignment(contract.id, assign40.id, coordinatorHeaders);

                const newShiftRes = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({
                        start_time: 1700700000,
                        end_time: 1700703600,
                    }),
                    coordinatorHeaders
                );
                const newShift = handleApiResponse<Shift>(newShiftRes, 201);

                const res = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(newShift.id, staff.id, { override_risk_check: true }),
                    accountManagerHeaders
                );
                const assignment = handleApiResponse<Assignment>(res, 201);

                expect(assignment.risk_override_penalty_applied).toBe(true);

                const contractCheckRes = await apiClient.getContract(contract.id, coordinatorHeaders);
                const updatedContract = handleApiResponse<StaffingContract>(contractCheckRes, 200);
                expect(updatedContract.compliance_risk_score).toBe(30);
            });
        });

        describe('P3-ASSIGN-NEXUS-01.16: Projected overtime at proposal (TCB-301)', () => {
            it('should calculate OT eligibility based on other PROPOSED shifts', async () => {
                const contract = await createAndActivateContract();
                const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders).then(r => handleApiResponse<Event>(r, 201));
                const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));

                const shift36 = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: 1700000000, end_time: 1700000000 + (36 * 3600) }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));
                await apiClient.createAssignment(contract.id, createAssignmentPayload(shift36.id, staff.id), accountManagerHeaders);

                const contractState1 = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));
                expect(contractState1.compliance_risk_score).toBe(0);

                const shift8 = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: 1700200000, end_time: 1700200000 + (8 * 3600) }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));

                const res = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift8.id, staff.id), accountManagerHeaders);
                const assignment = handleApiResponse<Assignment>(res, 201);

                expect(assignment.is_overtime_eligible).toBe(true);
                expect(assignment.provisional_cost).toBeCloseTo(200.00);

                const contractState2 = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));
                expect(contractState2.compliance_risk_score).toBe(5);
            });
        });
    });
});
