import {
    apiClient,
    buildUserHeaders,
    handleApiResponse,
    validateErrorEnvelope, assertStaffProfile,
    assertAssignment,
    assertConflictPairing,
    createContractPayload,
    createEventPayload,
    createShiftPayload,
    createStaffProfilePayload,
    createAssignmentPayload,
    createConflictPairingPayload, StaffingContract,
    Event,
    Shift,
    StaffProfile,
    Assignment,
    ConflictPairing,
    ContractStatus,
    EventStatus,
    ShiftStatus,
    AssignmentStatus,
    UserRole,
    CertificationType,
    ApiErrorId,
    createUnixTimestamp,
    addHours,
    subtractHours
} from '../../../test-helpers';

describe('Phase 6: Mixed Test Cases', () => {
    const coordinatorHeaders = buildUserHeaders('coordinator-1', UserRole.StaffingCoordinator);
    const staffMemberHeaders = buildUserHeaders('staff-1', UserRole.StaffMember);
    const accountManagerHeaders = buildUserHeaders('manager-1', UserRole.AccountManager);

    describe('P3-ASSIGN-NEXUS-01.14: Rest period violation - shift ends too close to existing shift', () => {
        it('should reject assignment if new shift ends less than 8 hours before existing shift begins', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Rest Period Test Contract' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);

            const activateRes = await apiClient.activateContract(contract.id, coordinatorHeaders);
            handleApiResponse<StaffingContract>(activateRes, 200);

            const staffRes = await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload({ first_name: 'Test', last_name: 'Staff' }),
                coordinatorHeaders
            );
            const staff = handleApiResponse<StaffProfile>(staffRes, 201);

            const eventRes = await apiClient.createEvent(
                contract.id,
                createEventPayload({ name: 'Rest Period Test Event' }),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);

            const day2At8AM = createUnixTimestamp(32);
            const existingShiftRes = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({
                    role_name: 'Existing Shift',
                    start_time: day2At8AM,
                    end_time: addHours(day2At8AM, 8),
                }),
                coordinatorHeaders
            );
            const existingShift = handleApiResponse<Shift>(existingShiftRes, 201);

            const existingAssignRes = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(existingShift.id, staff.id),
                accountManagerHeaders
            );
            const existingAssignment = handleApiResponse<Assignment>(existingAssignRes, 201);

            await apiClient.acceptAssignment(contract.id, existingAssignment.id, staffMemberHeaders);
            await apiClient.confirmAssignment(contract.id, existingAssignment.id, coordinatorHeaders);

            const day2At0001 = subtractHours(day2At8AM, 7 + 59 / 60);
            const newShiftRes = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({
                    role_name: 'New Shift',
                    start_time: subtractHours(day2At0001, 8),
                    end_time: day2At0001,
                }),
                coordinatorHeaders
            );
            const newShift = handleApiResponse<Shift>(newShiftRes, 201);

            const res = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(newShift.id, staff.id),
                accountManagerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_REST_PERIOD_VIOLATION });
        });
    });

    describe('P3-CONFIRM-ASSIGN-01.8: OT risk score is correctly decremented on confirmation', () => {
        it('should decrement compliance risk score when an assignment is no longer OT on confirmation', async () => {

            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Ledger Clamping Test', total_budget: 5000 }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            await apiClient.activateContract(contract.id, coordinatorHeaders);

            const staffRes = await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload({ base_pay_rate_per_hour: 20 }),
                coordinatorHeaders
            );
            const staff = handleApiResponse<StaffProfile>(staffRes, 201);

            const eventRes = await apiClient.createEvent(
                contract.id,
                createEventPayload(),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);

            const shiftARes = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({
                    role_name: 'Shift A',
                    start_time: createUnixTimestamp(24),
                    end_time: addHours(createUnixTimestamp(24), 35),
                }),
                coordinatorHeaders
            );
            const shiftA = handleApiResponse<Shift>(shiftARes, 201);

            const shiftBRes = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({
                    role_name: 'Shift B',
                    start_time: createUnixTimestamp(72),
                    end_time: addHours(createUnixTimestamp(72), 10),
                }),
                coordinatorHeaders
            );
            const shiftB = handleApiResponse<Shift>(shiftBRes, 201);

            const assignmentARes = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(shiftA.id, staff.id),
                accountManagerHeaders
            );
            const assignmentA = handleApiResponse<Assignment>(assignmentARes, 201);
            await apiClient.acceptAssignment(contract.id, assignmentA.id, staffMemberHeaders);

            const assignmentBRes = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(shiftB.id, staff.id),
                accountManagerHeaders
            );
            const assignmentB = handleApiResponse<Assignment>(assignmentBRes, 201);
            expect(assignmentB.is_overtime_eligible).toBe(true);

            await apiClient.acceptAssignment(contract.id, assignmentB.id, staffMemberHeaders);

            const contractBeforeCancel = await apiClient.getContract(contract.id, coordinatorHeaders);
            const contractData = handleApiResponse<StaffingContract>(contractBeforeCancel, 200);
            expect(contractData.compliance_risk_score).toBe(5);

            const cancelAssignmentARes = await apiClient.cancelAssignment(contract.id, assignmentA.id, coordinatorHeaders);
            handleApiResponse<Assignment>(cancelAssignmentARes, 200);

            const confirmRes = await apiClient.confirmAssignment(contract.id, assignmentB.id, coordinatorHeaders);
            handleApiResponse<Assignment>(confirmRes, 200);

            const finalContractRes = await apiClient.getContract(contract.id, coordinatorHeaders);
            const finalContract = handleApiResponse<StaffingContract>(finalContractRes, 200);
            expect(finalContract.compliance_risk_score).toBe(0);
        });
    });

    describe('TC-E2E-08: Conflict pairing created after assignments', () => {
        it('should prevent re-assignment when conflict is created after both staff are already assigned', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Conflict After Assignment Test' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            await apiClient.activateContract(contract.id, coordinatorHeaders);

            const eventRes = await apiClient.createEvent(
                contract.id,
                createEventPayload({ name: 'Conflict Test Event' }),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);

            const janeRes = await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload({ first_name: 'Jane', last_name: 'Doe' }),
                coordinatorHeaders
            );
            const jane = handleApiResponse<StaffProfile>(janeRes, 201);

            const johnRes = await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload({ first_name: 'John', last_name: 'Smith' }),
                coordinatorHeaders
            );
            const john = handleApiResponse<StaffProfile>(johnRes, 201);

            const shiftARes = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({ role_name: 'Shift A' }),
                coordinatorHeaders
            );
            const shiftA = handleApiResponse<Shift>(shiftARes, 201);

            const shiftBRes = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({ role_name: 'Shift B' }),
                coordinatorHeaders
            );
            const shiftB = handleApiResponse<Shift>(shiftBRes, 201);

            const assignmentARes = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(shiftA.id, jane.id),
                accountManagerHeaders
            );
            const assignmentA = handleApiResponse<Assignment>(assignmentARes, 201);
            await apiClient.acceptAssignment(contract.id, assignmentA.id, staffMemberHeaders);
            await apiClient.confirmAssignment(contract.id, assignmentA.id, coordinatorHeaders);

            const assignmentBRes = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(shiftB.id, john.id),
                accountManagerHeaders
            );
            const assignmentB = handleApiResponse<Assignment>(assignmentBRes, 201);
            await apiClient.acceptAssignment(contract.id, assignmentB.id, staffMemberHeaders);
            await apiClient.confirmAssignment(contract.id, assignmentB.id, coordinatorHeaders);

            const conflictRes = await apiClient.createConflictPairing(
                contract.id,
                createConflictPairingPayload(jane.id, john.id, { reason: 'Test conflict' }),
                coordinatorHeaders
            );
            handleApiResponse<ConflictPairing>(conflictRes, 201);

            await apiClient.cancelAssignment(contract.id, assignmentA.id, coordinatorHeaders);

            const res = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(shiftA.id, jane.id),
                accountManagerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INTERPERSONAL_CONFLICT });
        });
    });

    describe('P4-READONLY-01.1: Shift duration_hours readonly field', () => {
        it('should ignore user-provided duration_hours and calculate from timestamps', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Readonly Field Test' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            await apiClient.activateContract(contract.id, coordinatorHeaders);

            const eventRes = await apiClient.createEvent(
                contract.id,
                createEventPayload(),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);

            const startTime = 1700000000;
            const endTime = 1700018000;

            const shiftRes = await apiClient.createShift(
                contract.id,
                event.id,
                {
                    role_name: 'Server',
                    start_time: startTime,
                    end_time: endTime,
                    certification_needed: CertificationType.NONE,
                    duration_hours: 999,
                } as any,
                coordinatorHeaders
            );

            const shift = handleApiResponse<Shift>(shiftRes, 201);

            expect(shift.duration_hours).toBe(5.0);
        });
    });

    describe('P3-ASSIGN-NEXUS-01.15: Interpersonal conflict symmetrical check', () => {
        it('should reject assignment if conflicting staff member is already assigned', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Conflict Symmetry Test' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            await apiClient.activateContract(contract.id, coordinatorHeaders);

            const eventRes = await apiClient.createEvent(
                contract.id,
                createEventPayload(),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);

            const staff1Res = await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload({ first_name: 'Staff', last_name: 'One' }),
                coordinatorHeaders
            );
            const staff1 = handleApiResponse<StaffProfile>(staff1Res, 201);

            const staff2Res = await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload({ first_name: 'Staff', last_name: 'Two' }),
                coordinatorHeaders
            );
            const staff2 = handleApiResponse<StaffProfile>(staff2Res, 201);

            await apiClient.createConflictPairing(
                contract.id,
                createConflictPairingPayload(staff1.id, staff2.id),
                coordinatorHeaders
            );

            const shiftARes = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({ role_name: 'Shift A' }),
                coordinatorHeaders
            );
            const shiftA = handleApiResponse<Shift>(shiftARes, 201);

            const shiftBRes = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({ role_name: 'Shift B' }),
                coordinatorHeaders
            );
            const shiftB = handleApiResponse<Shift>(shiftBRes, 201);

            const assignmentBRes = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(shiftB.id, staff2.id),
                accountManagerHeaders
            );
            handleApiResponse<Assignment>(assignmentBRes, 201);

            const res = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(shiftA.id, staff1.id),
                accountManagerHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INTERPERSONAL_CONFLICT });
        });
    });

    describe('P3-ASSIGN-CREATE-XX: Rest period violation prevents assignment creation', () => {
        it('should reject assignment creation if it violates rest period with another ACCEPTED assignment', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Confirm Rest Period Test' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            await apiClient.activateContract(contract.id, coordinatorHeaders);

            const eventRes = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders);
            const event = handleApiResponse<Event>(eventRes, 201);

            const staffRes = await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload(),
                coordinatorHeaders
            );
            const staff = handleApiResponse<StaffProfile>(staffRes, 201);

            const shiftARes = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({
                    role_name: 'Shift A',
                    start_time: createUnixTimestamp(24 + 8),
                    end_time: createUnixTimestamp(24 + 10),
                }),
                coordinatorHeaders
            );
            const shiftA = handleApiResponse<Shift>(shiftARes, 201);

            const shiftBRes = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({
                    role_name: 'Shift B',
                    start_time: createUnixTimestamp(24 + 11),
                    end_time: createUnixTimestamp(24 + 14),
                }),
                coordinatorHeaders
            );
            const shiftB = handleApiResponse<Shift>(shiftBRes, 201);

            const assignmentARes = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(shiftA.id, staff.id),
                accountManagerHeaders
            );
            const assignmentA = handleApiResponse<Assignment>(assignmentARes, 201);
            await apiClient.acceptAssignment(contract.id, assignmentA.id, staffMemberHeaders);

            const assignmentBRes = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(shiftB.id, staff.id),
                accountManagerHeaders
            );
            validateErrorEnvelope(assignmentBRes, { expectedErrorId: ApiErrorId.ERR_REST_PERIOD_VIOLATION });
        });
    });

    describe('P3-CASCADE-CANCEL-01.2: Event cancellation cascades to shifts with no assignments', () => {
        it('should cascade cancellation to shifts even when they have no assignments', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Cascade Cancel Test' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            await apiClient.activateContract(contract.id, coordinatorHeaders);

            const eventRes = await apiClient.createEvent(
                contract.id,
                createEventPayload({ name: 'Event to Cancel' }),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);

            const shiftRes = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({ role_name: 'Unassigned Shift' }),
                coordinatorHeaders
            );
            const shift = handleApiResponse<Shift>(shiftRes, 201);
            expect(shift.status).toBe(ShiftStatus.OPEN);

            const cancelRes = await apiClient.updateEventStatus(
                contract.id,
                event.id,
                { status: EventStatus.CANCELLED },
                coordinatorHeaders
            );
            handleApiResponse<Event>(cancelRes, 200);

            const shiftAfterRes = await apiClient.getShift(contract.id, event.id, shift.id, coordinatorHeaders);
            const shiftAfter = handleApiResponse<Shift>(shiftAfterRes, 200);
            expect(shiftAfter.status).toBe(ShiftStatus.CANCELLED);
        });
    });

    describe('P3-CANCEL-ASSIGN-01.3: Cancel confirmed assignment on PLANNING event', () => {
        it('should reopen shift but not change PLANNING event status', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Cancel Assignment Test' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            await apiClient.activateContract(contract.id, coordinatorHeaders);

            const eventRes = await apiClient.createEvent(
                contract.id,
                createEventPayload(),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);

            const staffRes = await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload(),
                coordinatorHeaders
            );
            const staff = handleApiResponse<StaffProfile>(staffRes, 201);

            const shiftARes = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({ role_name: 'Shift A' }),
                coordinatorHeaders
            );
            const shiftA = handleApiResponse<Shift>(shiftARes, 201);

            const shiftBRes = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({ role_name: 'Shift B' }),
                coordinatorHeaders
            );
            const shiftB = handleApiResponse<Shift>(shiftBRes, 201);

            const assignmentARes = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(shiftA.id, staff.id),
                accountManagerHeaders
            );
            const assignmentA = handleApiResponse<Assignment>(assignmentARes, 201);
            await apiClient.acceptAssignment(contract.id, assignmentA.id, staffMemberHeaders);
            await apiClient.confirmAssignment(contract.id, assignmentA.id, coordinatorHeaders);

            const eventBeforeRes = await apiClient.getEvent(contract.id, event.id, coordinatorHeaders);
            const eventBefore = handleApiResponse<Event>(eventBeforeRes, 200);
            expect(eventBefore.status).toBe(EventStatus.PLANNING);

            const cancelRes = await apiClient.cancelAssignment(contract.id, assignmentA.id, coordinatorHeaders);
            const cancelledAssignment = handleApiResponse<Assignment>(cancelRes, 200);
            expect(cancelledAssignment.status).toBe(AssignmentStatus.CANCELLED);

            const shiftAAfterRes = await apiClient.getShift(contract.id, event.id, shiftA.id, coordinatorHeaders);
            const shiftAAfter = handleApiResponse<Shift>(shiftAAfterRes, 200);
            expect(shiftAAfter.status).toBe(ShiftStatus.OPEN);

            const eventAfterRes = await apiClient.getEvent(contract.id, event.id, coordinatorHeaders);
            const eventAfter = handleApiResponse<Event>(eventAfterRes, 200);
            expect(eventAfter.status).toBe(EventStatus.PLANNING);
        });
    });

    describe('TC-E2E-09: Payroll finalization OT risk penalty reconciliation', () => {
        it('should correctly reconcile risk score when OT status changes during payroll', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Payroll OT Test', total_budget: 10000 }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            await apiClient.activateContract(contract.id, coordinatorHeaders);

            const staffARes = await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload({ first_name: 'Staff', last_name: 'A', base_pay_rate_per_hour: 10 }),
                coordinatorHeaders
            );
            const staffA = handleApiResponse<StaffProfile>(staffARes, 201);

            const staffBRes = await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload({ first_name: 'Staff', last_name: 'B', base_pay_rate_per_hour: 10 }),
                coordinatorHeaders
            );
            const staffB = handleApiResponse<StaffProfile>(staffBRes, 201);

            const eventRes = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders);
            const event = handleApiResponse<Event>(eventRes, 201);

            const shiftA39Res = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({
                    start_time: createUnixTimestamp(24),
                    end_time: addHours(createUnixTimestamp(24), 39),
                }),
                coordinatorHeaders
            );
            const shiftA39 = handleApiResponse<Shift>(shiftA39Res, 201);

            const assignmentA39Res = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(shiftA39.id, staffA.id),
                accountManagerHeaders
            );
            const assignmentA39 = handleApiResponse<Assignment>(assignmentA39Res, 201);
            await apiClient.acceptAssignment(contract.id, assignmentA39.id, staffMemberHeaders);
            await apiClient.confirmAssignment(contract.id, assignmentA39.id, coordinatorHeaders);

            const shiftB2Res = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({
                    start_time: createUnixTimestamp(72),
                    end_time: addHours(createUnixTimestamp(72), 2),
                }),
                coordinatorHeaders
            );
            const shiftB2 = handleApiResponse<Shift>(shiftB2Res, 201);

            const assignmentB2Res = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(shiftB2.id, staffB.id),
                accountManagerHeaders
            );
            const assignmentB2 = handleApiResponse<Assignment>(assignmentB2Res, 201);
            await apiClient.acceptAssignment(contract.id, assignmentB2.id, staffMemberHeaders);
            await apiClient.confirmAssignment(contract.id, assignmentB2.id, coordinatorHeaders);

            const contractBefore = await apiClient.getContract(contract.id, coordinatorHeaders);
            const contractDataBefore = handleApiResponse<StaffingContract>(contractBefore, 200);
            expect(contractDataBefore.compliance_risk_score).toBe(0);

            const shiftA2Res = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({
                    start_time: createUnixTimestamp(96),
                    end_time: addHours(createUnixTimestamp(96), 2),
                }),
                coordinatorHeaders
            );
            const shiftA2 = handleApiResponse<Shift>(shiftA2Res, 201);

            const assignmentA2Res = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(shiftA2.id, staffA.id),
                accountManagerHeaders
            );
            const assignmentA2 = handleApiResponse<Assignment>(assignmentA2Res, 201);
            expect(assignmentA2.is_overtime_eligible).toBe(true);

            await apiClient.acceptAssignment(contract.id, assignmentA2.id, staffMemberHeaders);
            await apiClient.confirmAssignment(contract.id, assignmentA2.id, coordinatorHeaders);

            const contractAfterOT = await apiClient.getContract(contract.id, coordinatorHeaders);
            const contractDataAfterOT = handleApiResponse<StaffingContract>(contractAfterOT, 200);
            expect(contractDataAfterOT.compliance_risk_score).toBe(5);

            await apiClient.cancelAssignment(contract.id, assignmentA39.id, coordinatorHeaders);

            await apiClient.initiatePayroll(contract.id, coordinatorHeaders);

            const finalizeRes = await apiClient.finalizePayroll(contract.id, coordinatorHeaders);
            handleApiResponse<StaffingContract>(finalizeRes, 200);

            const contractFinalRes = await apiClient.getContract(contract.id, coordinatorHeaders);
            const contractDataFinal = handleApiResponse<StaffingContract>(contractFinalRes, 200);

            expect(contractDataFinal.compliance_risk_score).toBe(0);

            expect(contractDataFinal.status).toBe(ContractStatus.CLOSED);

            const assignmentA2FinalRes = await apiClient.getAssignment(contract.id, assignmentA2.id, coordinatorHeaders);
            const assignmentA2Final = handleApiResponse<Assignment>(assignmentA2FinalRes, 200);
            expect(assignmentA2Final.status).toBe(AssignmentStatus.PAID);
            expect(assignmentA2Final.final_payout).toBe(2 * 10);

            const assignmentB2FinalRes = await apiClient.getAssignment(contract.id, assignmentB2.id, coordinatorHeaders);
            const assignmentB2Final = handleApiResponse<Assignment>(assignmentB2FinalRes, 200);
            expect(assignmentB2Final.status).toBe(AssignmentStatus.PAID);
            expect(assignmentB2Final.final_payout).toBe(2 * 10);

            const totalPayout = assignmentA2Final.final_payout! + assignmentB2Final.final_payout!;
            expect(contractDataFinal.budget_balance).toBe(10000 - totalPayout);
        });
    });

    describe('P1-EVENT-02.2: List events for existing contract', () => {
        it('should successfully retrieve list of events for a contract', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Event List Test' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            await apiClient.activateContract(contract.id, coordinatorHeaders);

            const eventARes = await apiClient.createEvent(
                contract.id,
                createEventPayload({ name: 'Event A' }),
                coordinatorHeaders
            );
            const eventA = handleApiResponse<Event>(eventARes, 201);

            const eventBRes = await apiClient.createEvent(
                contract.id,
                createEventPayload({ name: 'Event B' }),
                coordinatorHeaders
            );
            const eventB = handleApiResponse<Event>(eventBRes, 201);

            const listRes = await apiClient.getEvents(contract.id, coordinatorHeaders);
            const events = handleApiResponse<Event[]>(listRes, 200, { expectPaginated: true });

            expect(events).toHaveLength(2);
            const eventIds = events.map(e => e.id);
            expect(eventIds).toContain(eventA.id);
            expect(eventIds).toContain(eventB.id);

            events.forEach(event => {
                expect(event.contract_id).toBe(contract.id);
            });
        });
    });

    describe('P1-SHIFT-03.1: List shifts for event', () => {
        it('should retrieve all shifts under an event', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Shift List Test' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            await apiClient.activateContract(contract.id, coordinatorHeaders);

            const eventRes = await apiClient.createEvent(
                contract.id,
                createEventPayload({ name: 'Multi-Shift Event' }),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);

            const shift1Res = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({ role_name: 'Shift 1' }),
                coordinatorHeaders
            );
            const shift1 = handleApiResponse<Shift>(shift1Res, 201);

            const shift2Res = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({ role_name: 'Shift 2' }),
                coordinatorHeaders
            );
            const shift2 = handleApiResponse<Shift>(shift2Res, 201);

            const listRes = await apiClient.getShifts(contract.id, event.id, coordinatorHeaders);
            const shifts = handleApiResponse<Shift[]>(listRes, 200, { expectPaginated: true });

            expect(shifts).toHaveLength(2);
            const shiftIds = shifts.map(s => s.id);
            expect(shiftIds).toContain(shift1.id);
            expect(shiftIds).toContain(shift2.id);
        });
    });

    describe('P1-ASSIGN-02.2: Get specific assignment', () => {
        it('should retrieve a specific assignment by ID within its contract', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Get Assignment Test' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            await apiClient.activateContract(contract.id, coordinatorHeaders);

            const eventRes = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders);
            const event = handleApiResponse<Event>(eventRes, 201);

            const shiftRes = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload(),
                coordinatorHeaders
            );
            const shift = handleApiResponse<Shift>(shiftRes, 201);

            const staffRes = await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload(),
                coordinatorHeaders
            );
            const staff = handleApiResponse<StaffProfile>(staffRes, 201);

            const assignmentRes = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(shift.id, staff.id),
                accountManagerHeaders
            );
            const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

            const getRes = await apiClient.getAssignment(contract.id, assignment.id, coordinatorHeaders);
            const retrieved = handleApiResponse<Assignment>(getRes, 200);

            assertAssignment(retrieved);
            expect(retrieved.id).toBe(assignment.id);
            expect(retrieved.contract_id).toBe(contract.id);
        });
    });

    describe('P1-ASSIGN-06.1: List all assignments for contract', () => {
        it('should list all assignments within a contract', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'List Assignments Test' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            await apiClient.activateContract(contract.id, coordinatorHeaders);

            const eventRes = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders);
            const event = handleApiResponse<Event>(eventRes, 201);

            const shift1Res = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({ role_name: 'Shift 1' }),
                coordinatorHeaders
            );
            const shift1 = handleApiResponse<Shift>(shift1Res, 201);

            const shift2Res = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({ role_name: 'Shift 2' }),
                coordinatorHeaders
            );
            const shift2 = handleApiResponse<Shift>(shift2Res, 201);

            const staff1Res = await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload({ first_name: 'Staff', last_name: 'One' }),
                coordinatorHeaders
            );
            const staff1 = handleApiResponse<StaffProfile>(staff1Res, 201);

            const staff2Res = await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload({ first_name: 'Staff', last_name: 'Two' }),
                coordinatorHeaders
            );
            const staff2 = handleApiResponse<StaffProfile>(staff2Res, 201);

            const assignment1Res = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(shift1.id, staff1.id),
                accountManagerHeaders
            );
            const assignment1 = handleApiResponse<Assignment>(assignment1Res, 201);

            const assignment2Res = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(shift2.id, staff2.id),
                accountManagerHeaders
            );
            const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);

            const listRes = await apiClient.getAssignments(contract.id, coordinatorHeaders);
            const assignments = handleApiResponse<Assignment[]>(listRes, 200, { expectPaginated: true });

            expect(assignments).toHaveLength(2);
            const assignmentIds = assignments.map(a => a.id);
            expect(assignmentIds).toContain(assignment1.id);
            expect(assignmentIds).toContain(assignment2.id);
        });
    });

    describe('P1-STAFF-04.1: List all staff profiles for contract', () => {
        it('should list all staff profiles within a contract', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'List Staff Test' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            await apiClient.activateContract(contract.id, coordinatorHeaders);

            const staffARes = await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload({ first_name: 'Staff', last_name: 'A' }),
                coordinatorHeaders
            );
            const staffA = handleApiResponse<StaffProfile>(staffARes, 201);

            const staffBRes = await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload({ first_name: 'Staff', last_name: 'B' }),
                coordinatorHeaders
            );
            const staffB = handleApiResponse<StaffProfile>(staffBRes, 201);

            const listRes = await apiClient.getStaffProfiles(contract.id, coordinatorHeaders);
            const staffProfiles = handleApiResponse<StaffProfile[]>(listRes, 200, { expectPaginated: true });

            expect(staffProfiles).toHaveLength(2);
            const staffIds = staffProfiles.map(s => s.id);
            expect(staffIds).toContain(staffA.id);
            expect(staffIds).toContain(staffB.id);
        });
    });

    describe('P1-CONFLICT-02.2: Get specific conflict pairing', () => {
        it('should retrieve a conflict pairing by ID within its contract', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Get Conflict Test' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            await apiClient.activateContract(contract.id, coordinatorHeaders);

            const staff1Res = await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload({ first_name: 'Staff', last_name: 'One' }),
                coordinatorHeaders
            );
            const staff1 = handleApiResponse<StaffProfile>(staff1Res, 201);

            const staff2Res = await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload({ first_name: 'Staff', last_name: 'Two' }),
                coordinatorHeaders
            );
            const staff2 = handleApiResponse<StaffProfile>(staff2Res, 201);

            const conflictRes = await apiClient.createConflictPairing(
                contract.id,
                createConflictPairingPayload(staff1.id, staff2.id, { reason: 'Test conflict' }),
                coordinatorHeaders
            );
            const conflict = handleApiResponse<ConflictPairing>(conflictRes, 201);

            const getRes = await apiClient.getConflictPairing(contract.id, conflict.id, coordinatorHeaders);
            const retrieved = handleApiResponse<ConflictPairing>(getRes, 200);

            assertConflictPairing(retrieved);
            expect(retrieved.id).toBe(conflict.id);
            expect(retrieved.contract_id).toBe(contract.id);
            expect(retrieved.reason).toBe('Test conflict');
        });
    });

    describe('P1-CONFLICT-03.1: List all conflict pairings for contract', () => {
        it('should list all conflict pairings within a contract', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'List Conflicts Test' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            await apiClient.activateContract(contract.id, coordinatorHeaders);

            const staff1Res = await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload({ first_name: 'Staff', last_name: 'One' }),
                coordinatorHeaders
            );
            const staff1 = handleApiResponse<StaffProfile>(staff1Res, 201);

            const staff2Res = await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload({ first_name: 'Staff', last_name: 'Two' }),
                coordinatorHeaders
            );
            const staff2 = handleApiResponse<StaffProfile>(staff2Res, 201);

            const staff3Res = await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload({ first_name: 'Staff', last_name: 'Three' }),
                coordinatorHeaders
            );
            const staff3 = handleApiResponse<StaffProfile>(staff3Res, 201);

            const conflict1Res = await apiClient.createConflictPairing(
                contract.id,
                createConflictPairingPayload(staff1.id, staff2.id),
                coordinatorHeaders
            );
            const conflict1 = handleApiResponse<ConflictPairing>(conflict1Res, 201);

            const conflict2Res = await apiClient.createConflictPairing(
                contract.id,
                createConflictPairingPayload(staff2.id, staff3.id),
                coordinatorHeaders
            );
            const conflict2 = handleApiResponse<ConflictPairing>(conflict2Res, 201);

            const listRes = await apiClient.getConflictPairings(contract.id, coordinatorHeaders);
            const conflicts = handleApiResponse<ConflictPairing[]>(listRes, 200, { expectPaginated: true });

            expect(conflicts).toHaveLength(2);
            const conflictIds = conflicts.map(c => c.id);
            expect(conflictIds).toContain(conflict1.id);
            expect(conflictIds).toContain(conflict2.id);
        });
    });

    describe('P3-CREATE-SHIFT-01.5: Shift duration_hours derived field', () => {
        it('should automatically populate and accurately calculate duration_hours', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Duration Hours Test' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            await apiClient.activateContract(contract.id, coordinatorHeaders);

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
                    role_name: 'Usher',
                    certification_needed: CertificationType.NONE,
                    start_time: 1700000000,
                    end_time: 1700010800,
                }),
                coordinatorHeaders
            );
            const shift = handleApiResponse<Shift>(shiftRes, 201);

            expect(shift.duration_hours).toBe(3.0);

            const getRes = await apiClient.getShift(contract.id, event.id, shift.id, coordinatorHeaders);
            const retrievedShift = handleApiResponse<Shift>(getRes, 200);
            expect(retrievedShift.duration_hours).toBe(3.0);
        });
    });

    describe('P2-PAGINATION-01: Pagination on list endpoints', () => {
        it('should respect limit and offset parameters and return correct metadata for the last page', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Pagination Test' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            await apiClient.activateContract(contract.id, coordinatorHeaders);

            await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload({ first_name: 'Staff', last_name: 'A' }),
                coordinatorHeaders
            );
            await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload({ first_name: 'Staff', last_name: 'B' }),
                coordinatorHeaders
            );
            const staffCRes = await apiClient.createStaffProfile(
                contract.id,
                createStaffProfilePayload({ first_name: 'Staff', last_name: 'C' }),
                coordinatorHeaders
            );
            const staffC = handleApiResponse<StaffProfile>(staffCRes, 201);

            const listRes = await apiClient.getStaffProfiles(contract.id, coordinatorHeaders, { limit: 1, offset: 2 });

            expect(listRes.status).toBe(200);
            expect(listRes.data.response_type).toBe('array');
            expect(listRes.data.meta.limit).toBe(1);
            expect(listRes.data.meta.offset).toBe(2);
            expect(listRes.data.meta.total_count).toBe(3);
            expect(listRes.data.meta.has_more).toBe(false);

            const staffProfiles = listRes.data.data as StaffProfile[];
            expect(staffProfiles).toHaveLength(1);
            expect(staffProfiles[0].id).toBe(staffC.id);
        });

        it('should return has_more: true when more records exist', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Pagination HasMore Test' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            await apiClient.activateContract(contract.id, coordinatorHeaders);

            await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders);
            await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders);
            await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders);

            const listRes = await apiClient.getStaffProfiles(contract.id, coordinatorHeaders, { limit: 2, offset: 0 });

            expect(listRes.status).toBe(200);
            expect(listRes.data.response_type).toBe('array');
            expect(listRes.data.meta.limit).toBe(2);
            expect(listRes.data.meta.offset).toBe(0);
            expect(listRes.data.meta.total_count).toBe(3);
            expect(listRes.data.meta.has_more).toBe(true);

            const staffProfiles = listRes.data.data as StaffProfile[];
            expect(staffProfiles).toHaveLength(2);
        });
    });

    describe('P3-EVENT-READY-01.5: Event cannot be ready with zero shifts', () => {
        it('should reject marking event ready when it has no shifts', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Zero Shift Event Test' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);

            await apiClient.activateContract(contract.id, coordinatorHeaders);

            const eventRes = await apiClient.createEvent(
                contract.id,
                createEventPayload({ name: 'Empty Event' }),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);

            const res = await apiClient.updateEventStatus(
                contract.id,
                event.id,
                { status: EventStatus.READY_FOR_EXECUTION },
                coordinatorHeaders
            );

            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SHIFTS_NOT_FILLED });
        });
    });

    describe('P3-CANCEL-ASSIGN-01.4: Cancelling assignment reverts READY_FOR_EXECUTION event to PLANNING', () => {
        it('should revert event status to PLANNING if a cancellation makes it no longer ready', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Event Revert Test' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            await apiClient.activateContract(contract.id, coordinatorHeaders);

            const eventRes = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders);
            const event = handleApiResponse<Event>(eventRes, 201);
            const shiftRes = await apiClient.createShift(contract.id, event.id, createShiftPayload(), coordinatorHeaders);
            const shift = handleApiResponse<Shift>(shiftRes, 201);

            const staffRes = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders);
            const staff = handleApiResponse<StaffProfile>(staffRes, 201);
            const assignmentRes = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(shift.id, staff.id),
                accountManagerHeaders
            );
            const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
            await apiClient.acceptAssignment(contract.id, assignment.id, staffMemberHeaders);
            await apiClient.confirmAssignment(contract.id, assignment.id, coordinatorHeaders);

            const readyRes = await apiClient.updateEventStatus(
                contract.id,
                event.id,
                { status: EventStatus.READY_FOR_EXECUTION },
                coordinatorHeaders
            );
            const readyEvent = handleApiResponse<Event>(readyRes, 200);
            expect(readyEvent.status).toBe(EventStatus.READY_FOR_EXECUTION);

            await apiClient.cancelAssignment(contract.id, assignment.id, coordinatorHeaders);

            const finalEventRes = await apiClient.getEvent(contract.id, event.id, coordinatorHeaders);
            const finalEvent = handleApiResponse<Event>(finalEventRes, 200);
            expect(finalEvent.status).toBe(EventStatus.PLANNING);
        });
    });

    describe('P3-ASSIGN-NEXUS-01.16: Rest period check ignores cancelled assignments', () => {
        it('should allow assignment when conflicting shift assignment was cancelled', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Rest Period Cancelled Test' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            await apiClient.activateContract(contract.id, coordinatorHeaders);
            const eventRes = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders);
            const event = handleApiResponse<Event>(eventRes, 201);
            const staffRes = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders);
            const staff = handleApiResponse<StaffProfile>(staffRes, 201);

            const shiftAStartTime = createUnixTimestamp(24);
            const shiftAEndTime = addHours(shiftAStartTime, 8);
            const shiftBStartTime = addHours(shiftAEndTime, 1);
            const shiftBEndTime = addHours(shiftBStartTime, 8);

            const shiftARes = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({ start_time: shiftAStartTime, end_time: shiftAEndTime }),
                coordinatorHeaders
            );
            const shiftA = handleApiResponse<Shift>(shiftARes, 201);

            const shiftBRes = await apiClient.createShift(
                contract.id,
                event.id,
                createShiftPayload({ start_time: shiftBStartTime, end_time: shiftBEndTime }),
                coordinatorHeaders
            );
            const shiftB = handleApiResponse<Shift>(shiftBRes, 201);

            const assignmentARes = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(shiftA.id, staff.id),
                accountManagerHeaders
            );
            const assignmentA = handleApiResponse<Assignment>(assignmentARes, 201);
            await apiClient.acceptAssignment(contract.id, assignmentA.id, staffMemberHeaders);
            await apiClient.confirmAssignment(contract.id, assignmentA.id, coordinatorHeaders);

            const failedAssignRes = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(shiftB.id, staff.id),
                accountManagerHeaders
            );
            validateErrorEnvelope(failedAssignRes, { expectedErrorId: ApiErrorId.ERR_REST_PERIOD_VIOLATION });

            await apiClient.cancelAssignment(contract.id, assignmentA.id, coordinatorHeaders);

            const successfulAssignRes = await apiClient.createAssignment(
                contract.id,
                createAssignmentPayload(shiftB.id, staff.id),
                accountManagerHeaders
            );

            const finalAssignment = handleApiResponse<Assignment>(successfulAssignRes, 201);
            expect(finalAssignment.shift_id).toBe(shiftB.id);
            expect(finalAssignment.staff_profile_id).toBe(staff.id);
        });
    });
});
