import {
    apiClient,
    buildUserHeaders,
    handleApiResponse,
    createContractPayload,
    createEventPayload,
    createShiftPayload,
    createStaffProfilePayload,
    createAssignmentPayload,
    StaffingContract,
    Event,
    Shift,
    StaffProfile,
    Assignment,
    EventStatus,
    ShiftStatus,
    AssignmentStatus,
    UserRole,
    createUnixTimestamp,
    addHours,
    ApiErrorId,
    validateErrorEnvelope,
    CertificationType,
    createConflictPairingPayload,
    ContractStatus,
    createAndActivateContract
} from '../../../test-helpers';

describe('Mixed Test Cases', () => {
    const coordinatorHeaders = buildUserHeaders('coordinator-1', UserRole.StaffingCoordinator);
    const accountManagerHeaders = buildUserHeaders('manager-1', UserRole.AccountManager);

    describe('TC-COMPLEX-02: Payroll Risk Reconciliation Test', () => {
        it('should correctly adjust compliance risk score during payroll finalization when OT status changes', async () => {
            const contract = await createAndActivateContract(3000.00);
            const contractId = contract.id;

            const eventRes = await apiClient.createEvent(
                contractId,
                createEventPayload({ name: 'Risk Reconciliation Event' }),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);
            const eventId = event.id;

            const staffRes = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'Risk',
                    last_name: 'Worker',
                    base_pay_rate_per_hour: 15.00
                }),
                coordinatorHeaders
            );
            const staff = handleApiResponse<StaffProfile>(staffRes, 201);
            const staffId = staff.id;

            const baseTime = createUnixTimestamp(24);

            const shiftARes = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Shift A - Provisionally OT',
                    start_time: baseTime,
                    end_time: addHours(baseTime, 42)
                }),
                coordinatorHeaders
            );
            const shiftA = handleApiResponse<Shift>(shiftARes, 201);

            const shiftBRes = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Shift B - To Be Cancelled',
                    start_time: addHours(baseTime, 50),
                    end_time: addHours(baseTime, 60)
                }),
                coordinatorHeaders
            );
            const shiftB = handleApiResponse<Shift>(shiftBRes, 201);

            const assignmentARes = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shiftA.id, staffId),
                accountManagerHeaders
            );
            const assignmentA = handleApiResponse<Assignment>(assignmentARes, 201);

            const assignmentBRes = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shiftB.id, staffId),
                accountManagerHeaders
            );
            const assignmentB = handleApiResponse<Assignment>(assignmentBRes, 201);

            expect(assignmentA.is_overtime_eligible).toBe(true);
            expect(assignmentB.is_overtime_eligible).toBe(true);

            const contractCheck1Res = await apiClient.getContract(contractId, coordinatorHeaders);
            const contractCheck1 = handleApiResponse<StaffingContract>(contractCheck1Res, 200);
            expect(contractCheck1.compliance_risk_score).toBe(10);

            const staffHeaders = buildUserHeaders('risk-worker', UserRole.StaffMember);
            await apiClient.acceptAssignment(contractId, assignmentA.id, staffHeaders);
            await apiClient.confirmAssignment(contractId, assignmentA.id, coordinatorHeaders);

            await apiClient.cancelAssignment(contractId, assignmentB.id, coordinatorHeaders);

            const contractCheck2Res = await apiClient.getContract(contractId, coordinatorHeaders);
            const contractCheck2 = handleApiResponse<StaffingContract>(contractCheck2Res, 200);
            expect(contractCheck2.compliance_risk_score).toBe(5);

            await apiClient.initiatePayroll(contractId, coordinatorHeaders);
            await apiClient.finalizePayroll(contractId, coordinatorHeaders);

            const finalAssignmentsRes = await apiClient.getAssignments(contractId, coordinatorHeaders);
            const finalAssignments = handleApiResponse<Assignment[]>(finalAssignmentsRes, 200, { expectPaginated: true });

            const finalAssignmentA = finalAssignments.find(a => a.id === assignmentA.id);
            const finalAssignmentB = finalAssignments.find(a => a.id === assignmentB.id);

            expect(finalAssignmentA?.is_overtime_eligible).toBe(true);
            expect(finalAssignmentA?.final_payout).toBe((40 * 15) + (2 * 15 * 1.5));

            expect(finalAssignmentB?.status).toBe(AssignmentStatus.CANCELLED);

            const finalContractRes = await apiClient.getContract(contractId, coordinatorHeaders);
            const finalContract = handleApiResponse<StaffingContract>(finalContractRes, 200);
            expect(finalContract.compliance_risk_score).toBe(5);
        });
    });

    describe('TC-COMPLEX-04: Cascading State Reversion Test', () => {
        it('should automatically revert event from READY_FOR_EXECUTION to PLANNING when assignment is cancelled', async () => {
            const contract = await createAndActivateContract(2000.00);
            const contractId = contract.id;

            const eventRes = await apiClient.createEvent(
                contractId,
                createEventPayload({ name: 'Cascading Reversion Event' }),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);
            const eventId = event.id;

            const staff1Res = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'Staff',
                    last_name: 'One',
                    base_pay_rate_per_hour: 20.00
                }),
                coordinatorHeaders
            );
            const staff1 = handleApiResponse<StaffProfile>(staff1Res, 201);

            const staff2Res = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'Staff',
                    last_name: 'Two',
                    base_pay_rate_per_hour: 22.00
                }),
                coordinatorHeaders
            );
            const staff2 = handleApiResponse<StaffProfile>(staff2Res, 201);

            const baseTime = createUnixTimestamp(24);

            const shift1Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Bartender',
                    start_time: baseTime,
                    end_time: addHours(baseTime, 8)
                }),
                coordinatorHeaders
            );
            const shift1 = handleApiResponse<Shift>(shift1Res, 201);

            const shift2Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Server',
                    start_time: addHours(baseTime, 2),
                    end_time: addHours(baseTime, 10)
                }),
                coordinatorHeaders
            );
            const shift2 = handleApiResponse<Shift>(shift2Res, 201);

            const shift3Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Manager',
                    start_time: addHours(baseTime, 16),
                    end_time: addHours(baseTime, 24)
                }),
                coordinatorHeaders
            );
            const shift3 = handleApiResponse<Shift>(shift3Res, 201);

            const assignment1Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift1.id, staff1.id),
                accountManagerHeaders
            );
            const assignment1 = handleApiResponse<Assignment>(assignment1Res, 201);

            const assignment2Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift2.id, staff2.id),
                accountManagerHeaders
            );
            const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);

            const assignment3Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift3.id, staff1.id),
                accountManagerHeaders
            );
            const assignment3 = handleApiResponse<Assignment>(assignment3Res, 201);

            const staff1Headers = buildUserHeaders('staff-one', UserRole.StaffMember);
            const staff2Headers = buildUserHeaders('staff-two', UserRole.StaffMember);

            await apiClient.acceptAssignment(contractId, assignment1.id, staff1Headers);
            await apiClient.confirmAssignment(contractId, assignment1.id, coordinatorHeaders);

            await apiClient.acceptAssignment(contractId, assignment2.id, staff2Headers);
            await apiClient.confirmAssignment(contractId, assignment2.id, coordinatorHeaders);

            await apiClient.acceptAssignment(contractId, assignment3.id, staff1Headers);
            await apiClient.confirmAssignment(contractId, assignment3.id, coordinatorHeaders);

            const shift1CheckRes = await apiClient.getShift(contractId, eventId, shift1.id, coordinatorHeaders);
            const shift1Check = handleApiResponse<Shift>(shift1CheckRes, 200);
            expect(shift1Check.status).toBe(ShiftStatus.FILLED);

            const shift2CheckRes = await apiClient.getShift(contractId, eventId, shift2.id, coordinatorHeaders);
            const shift2Check = handleApiResponse<Shift>(shift2CheckRes, 200);
            expect(shift2Check.status).toBe(ShiftStatus.FILLED);

            const shift3CheckRes = await apiClient.getShift(contractId, eventId, shift3.id, coordinatorHeaders);
            const shift3Check = handleApiResponse<Shift>(shift3CheckRes, 200);
            expect(shift3Check.status).toBe(ShiftStatus.FILLED);

            const eventUpdateRes = await apiClient.updateEventStatus(
                contractId,
                eventId,
                { status: EventStatus.READY_FOR_EXECUTION },
                coordinatorHeaders
            );
            const readyEvent = handleApiResponse<Event>(eventUpdateRes, 200);
            expect(readyEvent.status).toBe(EventStatus.READY_FOR_EXECUTION);

            await apiClient.cancelAssignment(contractId, assignment2.id, coordinatorHeaders);

            const shift2FinalCheckRes = await apiClient.getShift(contractId, eventId, shift2.id, coordinatorHeaders);
            const shift2FinalCheck = handleApiResponse<Shift>(shift2FinalCheckRes, 200);
            expect(shift2FinalCheck.status).toBe(ShiftStatus.OPEN);

            const eventFinalCheckRes = await apiClient.getEvent(contractId, eventId, coordinatorHeaders);
            const eventFinalCheck = handleApiResponse<Event>(eventFinalCheckRes, 200);
            expect(eventFinalCheck.status).toBe(EventStatus.PLANNING);
        });
    });
    describe('TC-EXTREME-01: Payroll Reconciliation with Provisional vs Final OT Mismatch', () => {
        it('should correctly reconcile when assignment loses OT status during final payroll calculation', async () => {
            const contract = await createAndActivateContract(3000.00);
            const contractId = contract.id;

            const eventRes = await apiClient.createEvent(
                contractId,
                createEventPayload({ name: 'OT Reconciliation Event' }),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);
            const eventId = event.id;

            const staffRes = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'Reconcile',
                    last_name: 'Worker',
                    base_pay_rate_per_hour: 20.00
                }),
                coordinatorHeaders
            );
            const staff = handleApiResponse<StaffProfile>(staffRes, 201);
            const staffId = staff.id;

            const baseTime = createUnixTimestamp(24);

            const shiftARes = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Shift A - Provisionally OT',
                    start_time: addHours(baseTime, 24),
                    end_time: addHours(baseTime, 66)
                }),
                coordinatorHeaders
            );
            const shiftA = handleApiResponse<Shift>(shiftARes, 201);

            const shiftBRes = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Shift B - To Be Cancelled',
                    start_time: baseTime,
                    end_time: addHours(baseTime, 10)
                }),
                coordinatorHeaders
            );
            const shiftB = handleApiResponse<Shift>(shiftBRes, 201);

            const assignmentARes = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shiftA.id, staffId),
                accountManagerHeaders
            );
            const assignmentA = handleApiResponse<Assignment>(assignmentARes, 201);

            const assignmentBRes = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shiftB.id, staffId),
                accountManagerHeaders
            );
            const assignmentB = handleApiResponse<Assignment>(assignmentBRes, 201);

            expect(assignmentA.is_overtime_eligible).toBe(true);
            expect(assignmentB.is_overtime_eligible).toBe(true);

            const contractCheck1Res = await apiClient.getContract(contractId, coordinatorHeaders);
            const contractCheck1 = handleApiResponse<StaffingContract>(contractCheck1Res, 200);
            expect(contractCheck1.compliance_risk_score).toBe(10);

            const staffHeaders = buildUserHeaders('reconcile-worker', UserRole.StaffMember);
            await apiClient.acceptAssignment(contractId, assignmentA.id, staffHeaders);
            await apiClient.confirmAssignment(contractId, assignmentA.id, coordinatorHeaders);

            await apiClient.declineAssignment(contractId, assignmentB.id, staffHeaders);

            const contractCheck2Res = await apiClient.getContract(contractId, coordinatorHeaders);
            const contractCheck2 = handleApiResponse<StaffingContract>(contractCheck2Res, 200);
            expect(contractCheck2.compliance_risk_score).toBe(5);

            await apiClient.initiatePayroll(contractId, coordinatorHeaders);
            await apiClient.finalizePayroll(contractId, coordinatorHeaders);

            const finalAssignmentsRes = await apiClient.getAssignments(contractId, coordinatorHeaders);
            const finalAssignments = handleApiResponse<Assignment[]>(finalAssignmentsRes, 200, { expectPaginated: true });

            const finalAssignmentA = finalAssignments.find(a => a.id === assignmentA.id);

            expect(finalAssignmentA?.is_overtime_eligible).toBe(true);
            expect(finalAssignmentA?.final_payout).toBe(860.00);

            const finalContractRes = await apiClient.getContract(contractId, coordinatorHeaders);
            const finalContract = handleApiResponse<StaffingContract>(finalContractRes, 200);
            expect(finalContract.compliance_risk_score).toBe(5);
        });
    });

    describe('TC-EXTREME-02: Complex Multi-Event Conflict Resolution', () => {
        it('should allow conflicted staff in different events but block in same event', async () => {
            const contract = await createAndActivateContract(5000.00);
            const contractId = contract.id;

            const event1Res = await apiClient.createEvent(
                contractId,
                createEventPayload({ name: 'Event 1' }),
                coordinatorHeaders
            );
            const event1 = handleApiResponse<Event>(event1Res, 201);

            const event2Res = await apiClient.createEvent(
                contractId,
                createEventPayload({ name: 'Event 2' }),
                coordinatorHeaders
            );
            const event2 = handleApiResponse<Event>(event2Res, 201);

            const staff1Res = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'Conflict',
                    last_name: 'One',
                    base_pay_rate_per_hour: 20.00
                }),
                coordinatorHeaders
            );
            const staff1 = handleApiResponse<StaffProfile>(staff1Res, 201);

            const staff2Res = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'Conflict',
                    last_name: 'Two',
                    base_pay_rate_per_hour: 22.00
                }),
                coordinatorHeaders
            );
            const staff2 = handleApiResponse<StaffProfile>(staff2Res, 201);

            const conflictRes = await apiClient.createConflictPairing(
                contractId,
                createConflictPairingPayload(staff1.id, staff2.id, { reason: 'Cannot work together' }),
                coordinatorHeaders
            );
            handleApiResponse(conflictRes, 201);

            const baseTime = createUnixTimestamp(24);

            const shift1Event1Res = await apiClient.createShift(
                contractId,
                event1.id,
                createShiftPayload({
                    role_name: 'Event1 Shift1',
                    start_time: baseTime,
                    end_time: addHours(baseTime, 8)
                }),
                coordinatorHeaders
            );
            const shift1Event1 = handleApiResponse<Shift>(shift1Event1Res, 201);

            const shift2Event1Res = await apiClient.createShift(
                contractId,
                event1.id,
                createShiftPayload({
                    role_name: 'Event1 Shift2',
                    start_time: addHours(baseTime, 2),
                    end_time: addHours(baseTime, 10)
                }),
                coordinatorHeaders
            );
            const shift2Event1 = handleApiResponse<Shift>(shift2Event1Res, 201);

            const shift1Event2Res = await apiClient.createShift(
                contractId,
                event2.id,
                createShiftPayload({
                    role_name: 'Event2 Shift1',
                    start_time: addHours(baseTime, 24),
                    end_time: addHours(baseTime, 32)
                }),
                coordinatorHeaders
            );
            const shift1Event2 = handleApiResponse<Shift>(shift1Event2Res, 201);

            const assignment1Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift1Event1.id, staff1.id),
                accountManagerHeaders
            );
            handleApiResponse<Assignment>(assignment1Res, 201);

            const assignment2Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift2Event1.id, staff2.id),
                accountManagerHeaders
            );

            validateErrorEnvelope(assignment2Res, {
                expectedErrorId: ApiErrorId.ERR_INTERPERSONAL_CONFLICT
            });

            const assignment3Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift1Event2.id, staff2.id),
                accountManagerHeaders
            );
            const assignment3 = handleApiResponse<Assignment>(assignment3Res, 201);

            expect(assignment3.staff_profile_id).toBe(staff2.id);
            expect(assignment3.status).toBe(AssignmentStatus.PROPOSED);
        });
    });

    describe('TC-EXTREME-03: Certification Validation with Multiple Requirements', () => {
        it('should handle complex certification scenarios with expired and missing certs', async () => {
            const contract = await createAndActivateContract(3000.00);
            const contractId = contract.id;

            const eventRes = await apiClient.createEvent(
                contractId,
                createEventPayload({ name: 'Certification Test Event' }),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);
            const eventId = event.id;

            const staffRes = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'Certified',
                    last_name: 'Worker',
                    base_pay_rate_per_hour: 20.00
                }),
                coordinatorHeaders
            );
            const staff = handleApiResponse<StaffProfile>(staffRes, 201);
            const staffId = staff.id;

            const certRes = await apiClient.addCertification(
                contractId,
                staffId,
                {
                    name: CertificationType.ALCOHOL_SERVICE_LICENSE,
                    issued_date: '2023-01-01',
                    expiry_date: '2030-12-31'
                },
                coordinatorHeaders
            );
            handleApiResponse<StaffProfile>(certRes, 201);

            const baseTime = createUnixTimestamp(24);

            const shift1Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Bartender',
                    certification_needed: CertificationType.ALCOHOL_SERVICE_LICENSE,
                    start_time: baseTime,
                    end_time: addHours(baseTime, 8)
                }),
                coordinatorHeaders
            );
            const shift1 = handleApiResponse<Shift>(shift1Res, 201);

            const assignment1Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift1.id, staffId),
                accountManagerHeaders
            );
            const assignment1 = handleApiResponse<Assignment>(assignment1Res, 201);
            expect(assignment1.status).toBe(AssignmentStatus.PROPOSED);

            const shift2Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Food Server',
                    certification_needed: CertificationType.FOOD_HANDLER_PERMIT,
                    start_time: addHours(baseTime, 10),
                    end_time: addHours(baseTime, 18)
                }),
                coordinatorHeaders
            );
            const shift2 = handleApiResponse<Shift>(shift2Res, 201);

            const assignment2Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift2.id, staffId),
                accountManagerHeaders
            );

            validateErrorEnvelope(assignment2Res, {
                expectedErrorId: ApiErrorId.ERR_CERTIFICATION_MISSING
            });

            const shift3Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'General Helper',
                    certification_needed: CertificationType.NONE,
                    start_time: addHours(baseTime, 20),
                    end_time: addHours(baseTime, 28)
                }),
                coordinatorHeaders
            );
            const shift3 = handleApiResponse<Shift>(shift3Res, 201);

            const assignment3Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift3.id, staffId),
                accountManagerHeaders
            );
            const assignment3 = handleApiResponse<Assignment>(assignment3Res, 201);
            expect(assignment3.status).toBe(AssignmentStatus.PROPOSED);
        });
    });

    describe('TC-EXTREME-04: Budget Precision at Penny Level', () => {
        it('should handle budget calculations with precise penny-level accuracy', async () => {
            const contract = await createAndActivateContract(100.01);
            const contractId = contract.id;

            const eventRes = await apiClient.createEvent(
                contractId,
                createEventPayload({ name: 'Penny Precision Event' }),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);
            const eventId = event.id;

            const staffRes = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'Penny',
                    last_name: 'Precise',
                    base_pay_rate_per_hour: 33.33
                }),
                coordinatorHeaders
            );
            const staff = handleApiResponse<StaffProfile>(staffRes, 201);
            const staffId = staff.id;

            const baseTime = createUnixTimestamp(24);

            const shift1Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Precise Shift',
                    start_time: baseTime,
                    end_time: baseTime + Math.floor(2.999 * 3600)
                }),
                coordinatorHeaders
            );
            const shift1 = handleApiResponse<Shift>(shift1Res, 201);

            const assignment1Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift1.id, staffId),
                accountManagerHeaders
            );
            const assignment1 = handleApiResponse<Assignment>(assignment1Res, 201);

            expect(assignment1.status).toBe(AssignmentStatus.PROPOSED);
            expect(assignment1.provisional_cost).toBeLessThanOrEqual(100.01);

            const shift2Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Tiny Shift',
                    start_time: addHours(baseTime, 11),
                    end_time: addHours(baseTime, 11) + 60
                }),
                coordinatorHeaders
            );
            const shift2 = handleApiResponse<Shift>(shift2Res, 201);

            const assignment2Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift2.id, staffId),
                accountManagerHeaders
            );

            validateErrorEnvelope(assignment2Res, {
                expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET
            });
        });
    });
    describe('TC-PAYROLL-02: Fractional Hours Overtime Calculation', () => {
        it('should correctly calculate overtime for fractional hours crossing 40-hour threshold', async () => {
            const contract = await createAndActivateContract(2000.00);
            const contractId = contract.id;

            const eventRes = await apiClient.createEvent(
                contractId,
                createEventPayload({ name: 'Fractional Hours Event' }),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);
            const eventId = event.id;

            const staffRes = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'Fractional',
                    last_name: 'Worker',
                    base_pay_rate_per_hour: 20.00
                }),
                coordinatorHeaders
            );
            const staff = handleApiResponse<StaffProfile>(staffRes, 201);
            const staffId = staff.id;

            const baseTime = createUnixTimestamp(24);

            const shift1Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Shift 1 - 39.5 hours',
                    start_time: baseTime,
                    end_time: baseTime + (39.5 * 3600)
                }),
                coordinatorHeaders
            );
            const shift1 = handleApiResponse<Shift>(shift1Res, 201);

            const shift2Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Shift 2 - 2.5 hours',
                    start_time: addHours(baseTime, 48),
                    end_time: addHours(baseTime, 50.5)
                }),
                coordinatorHeaders
            );
            const shift2 = handleApiResponse<Shift>(shift2Res, 201);

            const assignment1Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift1.id, staffId),
                accountManagerHeaders
            );
            const assignment1 = handleApiResponse<Assignment>(assignment1Res, 201);

            const assignment2Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift2.id, staffId),
                accountManagerHeaders
            );
            const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);

            const staffHeaders = buildUserHeaders('fractional-worker', UserRole.StaffMember);

            await apiClient.acceptAssignment(contractId, assignment1.id, staffHeaders);
            await apiClient.confirmAssignment(contractId, assignment1.id, coordinatorHeaders);

            await apiClient.acceptAssignment(contractId, assignment2.id, staffHeaders);
            await apiClient.confirmAssignment(contractId, assignment2.id, coordinatorHeaders);

            await apiClient.initiatePayroll(contractId, coordinatorHeaders);
            await apiClient.finalizePayroll(contractId, coordinatorHeaders);

            const finalAssignmentsRes = await apiClient.getAssignments(contractId, coordinatorHeaders);
            const finalAssignments = handleApiResponse<Assignment[]>(finalAssignmentsRes, 200, { expectPaginated: true });

            const finalAssignment1 = finalAssignments.find(a => a.id === assignment1.id);
            const finalAssignment2 = finalAssignments.find(a => a.id === assignment2.id);

            expect(finalAssignment1?.final_payout).toBe(790.00);
            expect(finalAssignment2?.final_payout).toBe(70.00);
            expect(finalAssignment1?.is_overtime_eligible).toBe(false);
            expect(finalAssignment2?.is_overtime_eligible).toBe(true);
        });
    });

    describe('TC-PAYROLL-03: Multiple Staff Members Overtime Isolation', () => {
        it('should calculate overtime separately for each staff member', async () => {
            const contract = await createAndActivateContract(5000.00);
            const contractId = contract.id;

            const eventRes = await apiClient.createEvent(
                contractId,
                createEventPayload({ name: 'Multiple Staff Event' }),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);
            const eventId = event.id;

            const staff1Res = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'Staff',
                    last_name: 'One',
                    base_pay_rate_per_hour: 15.00
                }),
                coordinatorHeaders
            );
            const staff1 = handleApiResponse<StaffProfile>(staff1Res, 201);

            const staff2Res = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'Staff',
                    last_name: 'Two',
                    base_pay_rate_per_hour: 25.00
                }),
                coordinatorHeaders
            );
            const staff2 = handleApiResponse<StaffProfile>(staff2Res, 201);

            const baseTime = createUnixTimestamp(24);

            const shift1Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Staff1 Shift1',
                    start_time: baseTime,
                    end_time: addHours(baseTime, 25)
                }),
                coordinatorHeaders
            );
            const shift1 = handleApiResponse<Shift>(shift1Res, 201);

            const shift2Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Staff1 Shift2',
                    start_time: addHours(baseTime, 33),
                    end_time: addHours(baseTime, 53)
                }),
                coordinatorHeaders
            );
            const shift2 = handleApiResponse<Shift>(shift2Res, 201);

            const shift3Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Staff2 Shift1',
                    start_time: addHours(baseTime, 60),
                    end_time: addHours(baseTime, 95)
                }),
                coordinatorHeaders
            );
            const shift3 = handleApiResponse<Shift>(shift3Res, 201);

            const assignment1Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift1.id, staff1.id),
                accountManagerHeaders
            );
            const assignment1 = handleApiResponse<Assignment>(assignment1Res, 201);

            const assignment2Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift2.id, staff1.id),
                accountManagerHeaders
            );
            const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);

            const assignment3Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift3.id, staff2.id),
                accountManagerHeaders
            );
            const assignment3 = handleApiResponse<Assignment>(assignment3Res, 201);

            const staff1Headers = buildUserHeaders('staff-one', UserRole.StaffMember);
            const staff2Headers = buildUserHeaders('staff-two', UserRole.StaffMember);

            await apiClient.acceptAssignment(contractId, assignment1.id, staff1Headers);
            await apiClient.confirmAssignment(contractId, assignment1.id, coordinatorHeaders);

            await apiClient.acceptAssignment(contractId, assignment2.id, staff1Headers);
            await apiClient.confirmAssignment(contractId, assignment2.id, coordinatorHeaders);

            await apiClient.acceptAssignment(contractId, assignment3.id, staff2Headers);
            await apiClient.confirmAssignment(contractId, assignment3.id, coordinatorHeaders);

            await apiClient.initiatePayroll(contractId, coordinatorHeaders);
            await apiClient.finalizePayroll(contractId, coordinatorHeaders);

            const finalAssignmentsRes = await apiClient.getAssignments(contractId, coordinatorHeaders);
            const finalAssignments = handleApiResponse<Assignment[]>(finalAssignmentsRes, 200, { expectPaginated: true });

            const finalAssignment1 = finalAssignments.find(a => a.id === assignment1.id);
            const finalAssignment2 = finalAssignments.find(a => a.id === assignment2.id);
            const finalAssignment3 = finalAssignments.find(a => a.id === assignment3.id);

            expect(finalAssignment1?.final_payout).toBe(375.00);
            expect(finalAssignment2?.final_payout).toBe(337.50);
            expect(finalAssignment3?.final_payout).toBe(875.00);

            expect(finalAssignment1?.is_overtime_eligible).toBe(false);
            expect(finalAssignment2?.is_overtime_eligible).toBe(true);
            expect(finalAssignment3?.is_overtime_eligible).toBe(false);
        });
    });
    describe('TC-STATE-01: Event Cancellation Cascade with Mixed Assignment States', () => {
        it('should cancel all assignments and revert all ledgers when event is cancelled', async () => {
            const contract = await createAndActivateContract(5000.00);
            const contractId = contract.id;

            const eventRes = await apiClient.createEvent(
                contractId,
                createEventPayload({ name: 'Cancellation Cascade Event' }),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);
            const eventId = event.id;

            const staff1Res = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'Staff',
                    last_name: 'One',
                    base_pay_rate_per_hour: 20.00
                }),
                coordinatorHeaders
            );
            const staff1 = handleApiResponse<StaffProfile>(staff1Res, 201);

            const staff2Res = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'Staff',
                    last_name: 'Two',
                    base_pay_rate_per_hour: 25.00
                }),
                coordinatorHeaders
            );
            const staff2 = handleApiResponse<StaffProfile>(staff2Res, 201);

            const baseTime = createUnixTimestamp(24);

            const shift1Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Shift 1',
                    start_time: baseTime,
                    end_time: addHours(baseTime, 45)
                }),
                coordinatorHeaders
            );
            const shift1 = handleApiResponse<Shift>(shift1Res, 201);

            const shift2Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Shift 2',
                    start_time: addHours(baseTime, 50),
                    end_time: addHours(baseTime, 58)
                }),
                coordinatorHeaders
            );
            const shift2 = handleApiResponse<Shift>(shift2Res, 201);

            const shift3Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Shift 3',
                    start_time: addHours(baseTime, 60),
                    end_time: addHours(baseTime, 68)
                }),
                coordinatorHeaders
            );
            const shift3 = handleApiResponse<Shift>(shift3Res, 201);

            const assignment1Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift1.id, staff1.id),
                accountManagerHeaders
            );
            const assignment1 = handleApiResponse<Assignment>(assignment1Res, 201);

            const assignment2Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift2.id, staff2.id),
                accountManagerHeaders
            );
            const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);

            const staff2Headers = buildUserHeaders('staff-two', UserRole.StaffMember);
            await apiClient.acceptAssignment(contractId, assignment2.id, staff2Headers);

            const assignment3Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift3.id, staff1.id),
                accountManagerHeaders
            );
            const assignment3 = handleApiResponse<Assignment>(assignment3Res, 201);

            const staff1Headers = buildUserHeaders('staff-one', UserRole.StaffMember);
            await apiClient.acceptAssignment(contractId, assignment3.id, staff1Headers);
            await apiClient.confirmAssignment(contractId, assignment3.id, coordinatorHeaders);

            const contractCheck1Res = await apiClient.getContract(contractId, coordinatorHeaders);
            const contractCheck1 = handleApiResponse<StaffingContract>(contractCheck1Res, 200);

            expect(contractCheck1.compliance_risk_score).toBe(5);
            expect(contractCheck1.budget_balance).toBeLessThan(5000.00);

            const eventCancelRes = await apiClient.updateEventStatus(
                contractId,
                eventId,
                { status: EventStatus.CANCELLED },
                coordinatorHeaders
            );
            const cancelledEvent = handleApiResponse<Event>(eventCancelRes, 200);
            expect(cancelledEvent.status).toBe(EventStatus.CANCELLED);

            const finalAssignmentsRes = await apiClient.getAssignments(contractId, coordinatorHeaders);
            const finalAssignments = handleApiResponse<Assignment[]>(finalAssignmentsRes, 200, { expectPaginated: true });

            const finalAssignment1 = finalAssignments.find(a => a.id === assignment1.id);
            const finalAssignment2 = finalAssignments.find(a => a.id === assignment2.id);
            const finalAssignment3 = finalAssignments.find(a => a.id === assignment3.id);

            expect(finalAssignment1?.status).toBe(AssignmentStatus.CANCELLED);
            expect(finalAssignment2?.status).toBe(AssignmentStatus.CANCELLED);
            expect(finalAssignment3?.status).toBe(AssignmentStatus.CANCELLED);

            const shift1CheckRes = await apiClient.getShift(contractId, eventId, shift1.id, coordinatorHeaders);
            const shift1Check = handleApiResponse<Shift>(shift1CheckRes, 200);
            expect(shift1Check.status).toBe(ShiftStatus.CANCELLED);

            const contractCheck2Res = await apiClient.getContract(contractId, coordinatorHeaders);
            const contractCheck2 = handleApiResponse<StaffingContract>(contractCheck2Res, 200);

            expect(contractCheck2.compliance_risk_score).toBe(0);
            expect(contractCheck2.budget_balance).toBe(5000.00);
        });
    });

    describe('TC-STATE-02: Assignment Decline After Acceptance', () => {
        it('should not allow declining an assignment that has already been accepted', async () => {
            const contract = await createAndActivateContract(2000.00);
            const contractId = contract.id;

            const eventRes = await apiClient.createEvent(
                contractId,
                createEventPayload({ name: 'Decline After Accept Event' }),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);
            const eventId = event.id;

            const staffRes = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'Confused',
                    last_name: 'Worker',
                    base_pay_rate_per_hour: 20.00
                }),
                coordinatorHeaders
            );
            const staff = handleApiResponse<StaffProfile>(staffRes, 201);
            const staffId = staff.id;

            const baseTime = createUnixTimestamp(24);

            const shiftRes = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Test Shift',
                    start_time: baseTime,
                    end_time: addHours(baseTime, 8)
                }),
                coordinatorHeaders
            );
            const shift = handleApiResponse<Shift>(shiftRes, 201);

            const assignmentRes = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift.id, staffId),
                accountManagerHeaders
            );
            const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

            const staffHeaders = buildUserHeaders('confused-worker', UserRole.StaffMember);
            await apiClient.acceptAssignment(contractId, assignment.id, staffHeaders);

            const declineRes = await apiClient.declineAssignment(contractId, assignment.id, staffHeaders);

            validateErrorEnvelope(declineRes, {
                expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_PROPOSED
            });

            const assignmentCheckRes = await apiClient.getAssignment(contractId, assignment.id, coordinatorHeaders);
            const assignmentCheck = handleApiResponse<Assignment>(assignmentCheckRes, 200);
            expect(assignmentCheck.status).toBe(AssignmentStatus.ACCEPTED);
        });
    });

    describe('TC-STATE-03: Confirmation After Cancellation', () => {
        it('should not allow confirming an assignment that has been cancelled', async () => {
            const contract = await createAndActivateContract(2000.00);
            const contractId = contract.id;

            const eventRes = await apiClient.createEvent(
                contractId,
                createEventPayload({ name: 'Confirm After Cancel Event' }),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);
            const eventId = event.id;

            const staffRes = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'Cancelled',
                    last_name: 'Worker',
                    base_pay_rate_per_hour: 20.00
                }),
                coordinatorHeaders
            );
            const staff = handleApiResponse<StaffProfile>(staffRes, 201);
            const staffId = staff.id;

            const baseTime = createUnixTimestamp(24);

            const shiftRes = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Test Shift',
                    start_time: baseTime,
                    end_time: addHours(baseTime, 8)
                }),
                coordinatorHeaders
            );
            const shift = handleApiResponse<Shift>(shiftRes, 201);

            const assignmentRes = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift.id, staffId),
                accountManagerHeaders
            );
            const assignment = handleApiResponse<Assignment>(assignmentRes, 201);

            const staffHeaders = buildUserHeaders('cancelled-worker', UserRole.StaffMember);
            await apiClient.acceptAssignment(contractId, assignment.id, staffHeaders);

            await apiClient.cancelAssignment(contractId, assignment.id, coordinatorHeaders);

            const confirmRes = await apiClient.confirmAssignment(contractId, assignment.id, coordinatorHeaders);

            validateErrorEnvelope(confirmRes, {
                expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_ACCEPTED
            });

            const assignmentCheckRes = await apiClient.getAssignment(contractId, assignment.id, coordinatorHeaders);
            const assignmentCheck = handleApiResponse<Assignment>(assignmentCheckRes, 200);
            expect(assignmentCheck.status).toBe(AssignmentStatus.CANCELLED);
        });
    });

    describe('TC-STATE-05: Payroll Initiation with Mixed Assignment States', () => {
        it('should block payroll initiation when assignments are in PROPOSED or ACCEPTED states', async () => {
            const contract = await createAndActivateContract(2000.00);
            const contractId = contract.id;

            const eventRes = await apiClient.createEvent(
                contractId,
                createEventPayload({ name: 'Mixed States Event' }),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);
            const eventId = event.id;

            const staffRes = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'Mixed',
                    last_name: 'States',
                    base_pay_rate_per_hour: 20.00
                }),
                coordinatorHeaders
            );
            const staff = handleApiResponse<StaffProfile>(staffRes, 201);
            const staffId = staff.id;

            const baseTime = createUnixTimestamp(24);

            const shift1Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Confirmed Shift',
                    start_time: baseTime,
                    end_time: addHours(baseTime, 8)
                }),
                coordinatorHeaders
            );
            const shift1 = handleApiResponse<Shift>(shift1Res, 201);

            const shift2Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Proposed Shift',
                    start_time: addHours(baseTime, 20),
                    end_time: addHours(baseTime, 28)
                }),
                coordinatorHeaders
            );
            const shift2 = handleApiResponse<Shift>(shift2Res, 201);

            const assignment1Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift1.id, staffId),
                accountManagerHeaders
            );
            const assignment1 = handleApiResponse<Assignment>(assignment1Res, 201);

            const staffHeaders = buildUserHeaders('mixed-states', UserRole.StaffMember);
            await apiClient.acceptAssignment(contractId, assignment1.id, staffHeaders);
            await apiClient.confirmAssignment(contractId, assignment1.id, coordinatorHeaders);

            const assignment2Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift2.id, staffId),
                accountManagerHeaders
            );
            handleApiResponse<Assignment>(assignment2Res, 201);

            const initiatePayrollRes = await apiClient.initiatePayroll(contractId, coordinatorHeaders);

            validateErrorEnvelope(initiatePayrollRes, {
                expectedErrorId: ApiErrorId.ERR_UNRESOLVED_ASSIGNMENTS_EXIST
            });

            const contractCheckRes = await apiClient.getContract(contractId, coordinatorHeaders);
            const contractCheck = handleApiResponse<StaffingContract>(contractCheckRes, 200);
            expect(contractCheck.status).toBe(ContractStatus.ACTIVE);
        });
    });
});
