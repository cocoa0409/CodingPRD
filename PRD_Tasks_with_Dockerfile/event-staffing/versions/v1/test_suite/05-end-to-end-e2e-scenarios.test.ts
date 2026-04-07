import {
    apiClient,
    buildUserHeaders,
    handleApiResponse,
    validateErrorEnvelope, createContractPayload,
    createEventPayload,
    createShiftPayload,
    createStaffProfilePayload,
    createAssignmentPayload,
    StaffingContract,
    Event,
    Shift,
    StaffProfile,
    Assignment,
    ContractStatus,
    EventStatus,
    ShiftStatus,
    AssignmentStatus,
    UserRole,
    ApiErrorId,
    createUnixTimestamp,
    addHours,
    setupBasicContract,
} from '../../../test-helpers';

describe('End-to-End Scenario Tests', () => {
    const coordinatorHeaders = buildUserHeaders('coordinator-1', UserRole.StaffingCoordinator);
    const accountManagerHeaders = buildUserHeaders('manager-1', UserRole.AccountManager);

    describe('TC-E2E-01: Perfect contract lifecycle', () => {
        it('should verify complete contract lifecycle with overtime, declined offer, backfill, and payroll', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({
                    client_name: 'Perfect Lifecycle Contract',
                    total_budget: 5000.00
                }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            const contractId = contract.id;

            const activateRes = await apiClient.activateContract(contractId, coordinatorHeaders);
            const activeContract = handleApiResponse<StaffingContract>(activateRes, 200);
            expect(activeContract.status).toBe(ContractStatus.ACTIVE);

            const janeRes = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'Jane',
                    last_name: 'Doe',
                    base_pay_rate_per_hour: 20.00
                }),
                coordinatorHeaders
            );
            const jane = handleApiResponse<StaffProfile>(janeRes, 201);
            const staffId_Jane = jane.id;

            const johnRes = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'John',
                    last_name: 'Smith',
                    base_pay_rate_per_hour: 22.00
                }),
                coordinatorHeaders
            );
            const john = handleApiResponse<StaffProfile>(johnRes, 201);
            const staffId_John = john.id;

            const eventRes = await apiClient.createEvent(
                contractId,
                createEventPayload({ name: 'Main Event' }),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);
            const eventId = event.id;

            const baseTime = createUnixTimestamp(24);

            const shiftARes = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Shift A - 10 hours',
                    start_time: baseTime,
                    end_time: addHours(baseTime, 10)
                }),
                coordinatorHeaders
            );
            const shiftA = handleApiResponse<Shift>(shiftARes, 201);
            const shiftId_A = shiftA.id;

            const shiftBRes = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Shift B - 40 hours',
                    start_time: addHours(baseTime, 24),
                    end_time: addHours(baseTime, 64)
                }),
                coordinatorHeaders
            );
            const shiftB = handleApiResponse<Shift>(shiftBRes, 201);
            const shiftId_B = shiftB.id;

            const assignmentA1Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shiftId_A, staffId_Jane),
                accountManagerHeaders
            );
            const assignmentA1 = handleApiResponse<Assignment>(assignmentA1Res, 201);
            const assignmentId_A1 = assignmentA1.id;

            const assignmentBRes = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shiftId_B, staffId_Jane),
                accountManagerHeaders
            );
            const assignmentB = handleApiResponse<Assignment>(assignmentBRes, 201);
            const assignmentId_B = assignmentB.id;

            const declineRes = await apiClient.declineAssignment(
                contractId,
                assignmentId_A1,
                buildUserHeaders('jane-doe', UserRole.StaffMember)
            );
            const declinedAssignment = handleApiResponse<Assignment>(declineRes, 200);
            expect(declinedAssignment.status).toBe(AssignmentStatus.DECLINED);

            const shiftACheckRes = await apiClient.getShift(contractId, eventId, shiftId_A, coordinatorHeaders);
            const shiftACheck = handleApiResponse<Shift>(shiftACheckRes, 200);
            expect(shiftACheck.status).toBe(ShiftStatus.OPEN);

            const assignmentBAfterDecline = await apiClient.getAssignment(contractId, assignmentB.id, coordinatorHeaders).then(res => handleApiResponse<Assignment>(res, 200));

            const contractCheck1Res = await apiClient.getContract(contractId, coordinatorHeaders);
            const contractCheck1 = handleApiResponse<StaffingContract>(contractCheck1Res, 200);
            expect(contractCheck1.budget_balance).toBe(5000 - assignmentBAfterDecline.provisional_cost);

            const assignmentA2Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shiftId_A, staffId_John),
                accountManagerHeaders
            );
            const assignmentA2 = handleApiResponse<Assignment>(assignmentA2Res, 201);
            const assignmentId_A2 = assignmentA2.id;

            const acceptA2Res = await apiClient.acceptAssignment(
                contractId,
                assignmentId_A2,
                buildUserHeaders('john-smith', UserRole.StaffMember)
            );
            const acceptedA2 = handleApiResponse<Assignment>(acceptA2Res, 200);
            expect(acceptedA2.status).toBe(AssignmentStatus.ACCEPTED);

            const acceptBRes = await apiClient.acceptAssignment(
                contractId,
                assignmentId_B,
                buildUserHeaders('jane-doe', UserRole.StaffMember)
            );
            const acceptedB = handleApiResponse<Assignment>(acceptBRes, 200);
            expect(acceptedB.status).toBe(AssignmentStatus.ACCEPTED);

            const confirmA2Res = await apiClient.confirmAssignment(
                contractId,
                assignmentId_A2,
                coordinatorHeaders
            );
            const confirmedA2 = handleApiResponse<Assignment>(confirmA2Res, 200);
            expect(confirmedA2.status).toBe(AssignmentStatus.CONFIRMED);

            const confirmBRes = await apiClient.confirmAssignment(
                contractId,
                assignmentId_B,
                coordinatorHeaders
            );
            const confirmedB = handleApiResponse<Assignment>(confirmBRes, 200);
            expect(confirmedB.status).toBe(AssignmentStatus.CONFIRMED);

            const shiftAFilledCheckRes = await apiClient.getShift(contractId, eventId, shiftId_A, coordinatorHeaders);
            const shiftAFilledCheck = handleApiResponse<Shift>(shiftAFilledCheckRes, 200);
            expect(shiftAFilledCheck.status).toBe(ShiftStatus.FILLED);

            const shiftBFilledCheckRes = await apiClient.getShift(contractId, eventId, shiftId_B, coordinatorHeaders);
            const shiftBFilledCheck = handleApiResponse<Shift>(shiftBFilledCheckRes, 200);
            expect(shiftBFilledCheck.status).toBe(ShiftStatus.FILLED);

            expect(confirmedA2.provisional_cost).toBe(220.00);

            expect(confirmedB.provisional_cost).toBe(800.00);
            expect(confirmedB.is_overtime_eligible).toBe(false);

            const contractCheck2Res = await apiClient.getContract(contractId, coordinatorHeaders);
            const contractCheck2 = handleApiResponse<StaffingContract>(contractCheck2Res, 200);
            expect(contractCheck2.compliance_risk_score).toBe(0);
            expect(contractCheck2.budget_balance).toBe(5000 - 220 - 800);

            const eventUpdateRes = await apiClient.updateEventStatus(
                contractId,
                eventId,
                { status: EventStatus.READY_FOR_EXECUTION },
                coordinatorHeaders
            );
            const readyEvent = handleApiResponse<Event>(eventUpdateRes, 200);
            expect(readyEvent.status).toBe(EventStatus.READY_FOR_EXECUTION);

            const initiatePayrollRes = await apiClient.initiatePayroll(contractId, coordinatorHeaders);
            const payrollPendingContract = handleApiResponse<StaffingContract>(initiatePayrollRes, 200);
            expect(payrollPendingContract.status).toBe(ContractStatus.PAYROLL_PENDING);

            const finalizePayrollRes = await apiClient.finalizePayroll(contractId, coordinatorHeaders);
            const closedContract = handleApiResponse<StaffingContract>(finalizePayrollRes, 200);
            expect(closedContract.status).toBe(ContractStatus.CLOSED);

            const finalAssignmentsRes = await apiClient.getAssignments(contractId, coordinatorHeaders);
            const finalAssignments = handleApiResponse<Assignment[]>(finalAssignmentsRes, 200, { expectPaginated: true });

            const finalJohnAssignment = finalAssignments.find(a => a.id === assignmentId_A2);
            const finalJaneAssignment = finalAssignments.find(a => a.id === assignmentId_B);

            expect(finalJohnAssignment?.status).toBe(AssignmentStatus.PAID);
            expect(finalJohnAssignment?.final_payout).toBe(220.00);

            expect(finalJaneAssignment?.status).toBe(AssignmentStatus.PAID);
            expect(finalJaneAssignment?.final_payout).toBe(800.00);

            expect(closedContract.budget_balance).toBe(3980.00);
        });
    });

    describe('TC-E2E-02: Assignment overtime re-evaluation at confirmation', () => {
        it('should correctly re-evaluate overtime status when another proposed assignment is declined', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({
                    client_name: 'Overtime Re-evaluation Test',
                    total_budget: 10000.00
                }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            const contractId = contract.id;

            await apiClient.activateContract(contractId, coordinatorHeaders);

            const staffRes = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'S',
                    last_name: 'Worker',
                    base_pay_rate_per_hour: 10.00
                }),
                coordinatorHeaders
            );
            const staff = handleApiResponse<StaffProfile>(staffRes, 201);
            const staffId_S = staff.id;

            const eventRes = await apiClient.createEvent(
                contractId,
                createEventPayload({ name: 'Test Event' }),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);
            const eventId = event.id;

            const baseTime = createUnixTimestamp(24);

            const shiftARes = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Shift A - 39 hours',
                    start_time: baseTime,
                    end_time: addHours(baseTime, 39)
                }),
                coordinatorHeaders
            );
            const shiftA = handleApiResponse<Shift>(shiftARes, 201);
            const shiftId_A = shiftA.id;

            const shiftBRes = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Shift B - 2 hours',
                    start_time: addHours(baseTime, 50),
                    end_time: addHours(baseTime, 52)
                }),
                coordinatorHeaders
            );
            const shiftB = handleApiResponse<Shift>(shiftBRes, 201);
            const shiftId_B = shiftB.id;

            const assignmentARes = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shiftId_A, staffId_S),
                accountManagerHeaders
            );
            const assignmentA = handleApiResponse<Assignment>(assignmentARes, 201);
            const assignmentId_A = assignmentA.id;

            const assignmentBRes = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shiftId_B, staffId_S),
                accountManagerHeaders
            );
            const assignmentB = handleApiResponse<Assignment>(assignmentBRes, 201);
            const assignmentId_B = assignmentB.id;

            expect(assignmentB.is_overtime_eligible).toBe(true);
            expect(assignmentB.provisional_cost).toBe(25.00);

            const contractCheck1Res = await apiClient.getContract(contractId, coordinatorHeaders);
            const contractCheck1 = handleApiResponse<StaffingContract>(contractCheck1Res, 200);
            expect(contractCheck1.compliance_risk_score).toBe(5);

            await apiClient.declineAssignment(
                contractId,
                assignmentId_A,
                buildUserHeaders('s-worker', UserRole.StaffMember)
            );

            const shiftACheckRes = await apiClient.getShift(contractId, eventId, shiftId_A, coordinatorHeaders);
            const shiftACheck = handleApiResponse<Shift>(shiftACheckRes, 200);
            expect(shiftACheck.status).toBe(ShiftStatus.OPEN);

            await apiClient.acceptAssignment(
                contractId,
                assignmentId_B,
                buildUserHeaders('s-worker', UserRole.StaffMember)
            );

            const confirmBRes = await apiClient.confirmAssignment(
                contractId,
                assignmentId_B,
                coordinatorHeaders
            );
            const confirmedB = handleApiResponse<Assignment>(confirmBRes, 200);

            expect(confirmedB.status).toBe(AssignmentStatus.CONFIRMED);
            expect(confirmedB.is_overtime_eligible).toBe(false);
            expect(confirmedB.provisional_cost).toBe(20.00);

            const contractCheck2Res = await apiClient.getContract(contractId, coordinatorHeaders);
            const contractCheck2 = handleApiResponse<StaffingContract>(contractCheck2Res, 200);
            expect(contractCheck2.compliance_risk_score).toBe(0);
        });
    });

    describe('TC-E2E-03: Event cancellation with risk override', () => {
        it('should correctly revert all ledgers when cancelling event with mixed assignments', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({
                    client_name: 'Event Cancellation Test',
                    total_budget: 10000.00
                }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            const contractId = contract.id;

            await apiClient.activateContract(contractId, coordinatorHeaders);

            const staffARes = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'Staff',
                    last_name: 'A',
                    base_pay_rate_per_hour: 20.00
                }),
                coordinatorHeaders
            );
            const staffA = handleApiResponse<StaffProfile>(staffARes, 201);
            const staffId_A = staffA.id;

            const staffBRes = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'Staff',
                    last_name: 'B',
                    base_pay_rate_per_hour: 25.00
                }),
                coordinatorHeaders
            );
            const staffB = handleApiResponse<StaffProfile>(staffBRes, 201);
            const staffId_B = staffB.id;

            const setupEventRes = await apiClient.createEvent(
                contractId,
                createEventPayload({ name: 'Setup Event' }),
                coordinatorHeaders
            );
            const setupEvent = handleApiResponse<Event>(setupEventRes, 201);

            const baseTime = createUnixTimestamp(24);

            const otShiftRes = await apiClient.createShift(
                contractId,
                setupEvent.id,
                createShiftPayload({
                    role_name: 'OT Shift 1',
                    start_time: baseTime,
                    end_time: addHours(baseTime, 50)
                }),
                coordinatorHeaders
            );
            const otShift = handleApiResponse<Shift>(otShiftRes, 201);
            const assignRes = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(otShift.id, staffId_B),
                accountManagerHeaders
            );
            const assignObj = handleApiResponse<Assignment>(assignRes, 201);
            await apiClient.acceptAssignment(contractId, assignObj.id, buildUserHeaders('staff-b', UserRole.StaffMember));
            await apiClient.confirmAssignment(contractId, assignObj.id, coordinatorHeaders);

            for (let i = 1; i < 3; i++) {
                const shiftRes = await apiClient.createShift(
                    contractId,
                    setupEvent.id,
                    createShiftPayload({
                        role_name: `OT Shift ${i + 1}`,
                        start_time: addHours(baseTime, i * 60),
                        end_time: addHours(baseTime, i * 60 + 50)
                    }),
                    coordinatorHeaders
                );
                const otShift = handleApiResponse<Shift>(shiftRes, 201);
                const assignRes = await apiClient.createAssignment(
                    contractId,
                    createAssignmentPayload(otShift.id, staffId_B, { override_risk_check: true }),
                    accountManagerHeaders
                );
                const assignObj = handleApiResponse<Assignment>(assignRes, 201);
                await apiClient.acceptAssignment(contractId, assignObj.id, buildUserHeaders('staff-b', UserRole.StaffMember));
                await apiClient.confirmAssignment(contractId, assignObj.id, coordinatorHeaders);
            }

            const contractCheck1Res = await apiClient.getContract(contractId, coordinatorHeaders);
            const contractCheck1 = handleApiResponse<StaffingContract>(contractCheck1Res, 200);
            expect(contractCheck1.compliance_risk_score).toBe(15);

            const mainEventRes = await apiClient.createEvent(
                contractId,
                createEventPayload({ name: 'Main Event' }),
                coordinatorHeaders
            );
            const mainEvent = handleApiResponse<Event>(mainEventRes, 201);
            const eventId = mainEvent.id;

            const shift1Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Shift 1 - 4 hours',
                    start_time: addHours(baseTime, 200),
                    end_time: addHours(baseTime, 204)
                }),
                coordinatorHeaders
            );
            const shift1 = handleApiResponse<Shift>(shift1Res, 201);
            const shiftId_1 = shift1.id;

            const shift2Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Shift 2 - 40 hours',
                    start_time: addHours(baseTime, 220),
                    end_time: addHours(baseTime, 260)
                }),
                coordinatorHeaders
            );
            const shift2 = handleApiResponse<Shift>(shift2Res, 201);
            const shiftId_2 = shift2.id;

            const shift3Res = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Shift 3 - 5 hours',
                    start_time: addHours(baseTime, 270),
                    end_time: addHours(baseTime, 275)
                }),
                coordinatorHeaders
            );
            const shift3 = handleApiResponse<Shift>(shift3Res, 201);
            const shiftId_3 = shift3.id;

            const assignment1Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shiftId_1, staffId_A),
                accountManagerHeaders
            );
            const assignment1 = handleApiResponse<Assignment>(assignment1Res, 201);

            await apiClient.acceptAssignment(contractId, assignment1.id, buildUserHeaders('staff-a', UserRole.StaffMember));
            await apiClient.confirmAssignment(contractId, assignment1.id, coordinatorHeaders);

            const assignment2FailRes = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shiftId_2, staffId_B, { override_risk_check: false }),
                accountManagerHeaders
            );
            validateErrorEnvelope(assignment2FailRes, {
                expectedErrorId: ApiErrorId.ERR_RISK_THRESHOLD_EXCEEDED,
            });

            const assignment2Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shiftId_2, staffId_B, { override_risk_check: true }),
                accountManagerHeaders
            );
            const assignment2 = handleApiResponse<Assignment>(assignment2Res, 201);
            await apiClient.acceptAssignment(contractId, assignment2.id, buildUserHeaders('staff-b', UserRole.StaffMember));

            const assignment3Res = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shiftId_3, staffId_A),
                accountManagerHeaders
            );
            const assignment3 = handleApiResponse<Assignment>(assignment3Res, 201);

            const confirmedA1Res = await apiClient.getAssignment(contractId, assignment1.id, coordinatorHeaders);
            const confirmedA1 = handleApiResponse<Assignment>(confirmedA1Res, 200);
            expect(confirmedA1.provisional_cost).toBe(80.00);

            expect(assignment2.is_overtime_eligible).toBe(true);
            expect(assignment2.risk_override_penalty_applied).toBe(true);
            expect(assignment2.provisional_cost).toBe(1500.00);

            expect(assignment3.is_overtime_eligible).toBe(false);
            expect(assignment3.provisional_cost).toBe(100.00);

            const contractCheck2Res = await apiClient.getContract(contractId, coordinatorHeaders);
            const contractCheck2 = handleApiResponse<StaffingContract>(contractCheck2Res, 200);
            expect(contractCheck2.compliance_risk_score).toBe(30);

            const cancelRes = await apiClient.updateEventStatus(
                contractId,
                eventId,
                { status: EventStatus.CANCELLED },
                coordinatorHeaders
            );
            const cancelledEvent = handleApiResponse<Event>(cancelRes, 200);
            expect(cancelledEvent.status).toBe(EventStatus.CANCELLED);

            const eventCheckRes = await apiClient.getEvent(contractId, eventId, coordinatorHeaders);
            const eventCheck = handleApiResponse<Event>(eventCheckRes, 200);
            expect(eventCheck.status).toBe(EventStatus.CANCELLED);

            const shift1CheckRes = await apiClient.getShift(contractId, eventId, shiftId_1, coordinatorHeaders);
            const shift1Check = handleApiResponse<Shift>(shift1CheckRes, 200);
            expect(shift1Check.status).toBe(ShiftStatus.CANCELLED);

            const shift2CheckRes = await apiClient.getShift(contractId, eventId, shiftId_2, coordinatorHeaders);
            const shift2Check = handleApiResponse<Shift>(shift2CheckRes, 200);
            expect(shift2Check.status).toBe(ShiftStatus.CANCELLED);

            const shift3CheckRes = await apiClient.getShift(contractId, eventId, shiftId_3, coordinatorHeaders);
            const shift3Check = handleApiResponse<Shift>(shift3CheckRes, 200);
            expect(shift3Check.status).toBe(ShiftStatus.CANCELLED);

            const assignment1CheckRes = await apiClient.getAssignment(contractId, assignment1.id, coordinatorHeaders);
            const assignment1Check = handleApiResponse<Assignment>(assignment1CheckRes, 200);
            expect(assignment1Check.status).toBe(AssignmentStatus.CANCELLED);

            const assignment2CheckRes = await apiClient.getAssignment(contractId, assignment2.id, coordinatorHeaders);
            const assignment2Check = handleApiResponse<Assignment>(assignment2CheckRes, 200);
            expect(assignment2Check.status).toBe(AssignmentStatus.CANCELLED);

            const assignment3CheckRes = await apiClient.getAssignment(contractId, assignment3.id, coordinatorHeaders);
            const assignment3Check = handleApiResponse<Assignment>(assignment3CheckRes, 200);
            expect(assignment3Check.status).toBe(AssignmentStatus.CANCELLED);

            const contractCheck3Res = await apiClient.getContract(contractId, coordinatorHeaders);
            const contractCheck3 = handleApiResponse<StaffingContract>(contractCheck3Res, 200);
            expect(contractCheck3.compliance_risk_score).toBe(15);
            expect(contractCheck3.budget_balance).toBe(4875.00);
        });
    });

    describe('TC-E2E-06: Rest period violation at assignment creation with accepted assignment', () => {
        it('should fail to create an assignment that violates rest period with another accepted assignment', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({
                    client_name: 'Rest Period Violation Test',
                    total_budget: 10000.00
                }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            const contractId = contract.id;
            await apiClient.activateContract(contractId, coordinatorHeaders);

            const staffRes = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({ first_name: 'S', last_name: 'Worker', base_pay_rate_per_hour: 20.00 }),
                coordinatorHeaders
            );
            const staff = handleApiResponse<StaffProfile>(staffRes, 201);
            const staffId_S = staff.id;

            const eventRes = await apiClient.createEvent(contractId, createEventPayload({ name: 'Rest Period Event' }), coordinatorHeaders);
            const event = handleApiResponse<Event>(eventRes, 201);
            const eventId = event.id;

            const day1_8am = createUnixTimestamp(24);
            const day1_10am = addHours(day1_8am, 2);
            const day1_12pm = addHours(day1_10am, 2);
            const day1_2pm = addHours(day1_12pm, 2);

            const shiftARes = await apiClient.createShift(contractId, eventId, createShiftPayload({ role_name: 'Shift A', start_time: day1_8am, end_time: day1_10am }), coordinatorHeaders);
            const shiftA = handleApiResponse<Shift>(shiftARes, 201);

            const shiftBRes = await apiClient.createShift(contractId, eventId, createShiftPayload({ role_name: 'Shift B', start_time: day1_12pm, end_time: day1_2pm }), coordinatorHeaders);
            const shiftB = handleApiResponse<Shift>(shiftBRes, 201);

            const assignmentARes = await apiClient.createAssignment(contractId, createAssignmentPayload(shiftA.id, staffId_S), accountManagerHeaders);
            const assignmentA = handleApiResponse<Assignment>(assignmentARes, 201);
            await apiClient.acceptAssignment(contractId, assignmentA.id, buildUserHeaders('s-worker', UserRole.StaffMember));

            const assignmentBRes = await apiClient.createAssignment(contractId, createAssignmentPayload(shiftB.id, staffId_S), accountManagerHeaders);
            validateErrorEnvelope(assignmentBRes, { expectedErrorId: ApiErrorId.ERR_REST_PERIOD_VIOLATION });
        });
    });

    describe('TC-E2E-07: Final payroll reconciliation when OT status changes', () => {
        it('should correctly reconcile ledgers when assignment OT status changes between confirmation and payroll', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({
                    client_name: 'Payroll Reconciliation Test',
                    total_budget: 10000.00
                }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            const contractId = contract.id;

            await apiClient.activateContract(contractId, coordinatorHeaders);

            const staffRes = await apiClient.createStaffProfile(
                contractId,
                createStaffProfilePayload({
                    first_name: 'S',
                    last_name: 'Worker',
                    base_pay_rate_per_hour: 20.00
                }),
                coordinatorHeaders
            );
            const staff = handleApiResponse<StaffProfile>(staffRes, 201);
            const staffId_S = staff.id;

            const eventRes = await apiClient.createEvent(
                contractId,
                createEventPayload({ name: 'Reconciliation Event' }),
                coordinatorHeaders
            );
            const event = handleApiResponse<Event>(eventRes, 201);
            const eventId = event.id;

            const baseTime = createUnixTimestamp(24);

            const shiftARes = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Shift A - 39 hours',
                    start_time: baseTime,
                    end_time: addHours(baseTime, 39)
                }),
                coordinatorHeaders
            );
            const shiftA = handleApiResponse<Shift>(shiftARes, 201);
            const shiftId_A = shiftA.id;

            const shiftBRes = await apiClient.createShift(
                contractId,
                eventId,
                createShiftPayload({
                    role_name: 'Shift B - 2 hours',
                    start_time: addHours(baseTime, 50),
                    end_time: addHours(baseTime, 52)
                }),
                coordinatorHeaders
            );
            const shiftB = handleApiResponse<Shift>(shiftBRes, 201);
            const shiftId_B = shiftB.id;

            const assignmentARes = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shiftId_A, staffId_S),
                accountManagerHeaders
            );
            const assignmentA = handleApiResponse<Assignment>(assignmentARes, 201);

            await apiClient.acceptAssignment(contractId, assignmentA.id, buildUserHeaders('s-worker', UserRole.StaffMember));
            await apiClient.confirmAssignment(contractId, assignmentA.id, coordinatorHeaders);

            const assignmentBRes = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shiftId_B, staffId_S),
                accountManagerHeaders
            );
            const assignmentB = handleApiResponse<Assignment>(assignmentBRes, 201);

            await apiClient.acceptAssignment(contractId, assignmentB.id, buildUserHeaders('s-worker', UserRole.StaffMember));

            const confirmBRes = await apiClient.confirmAssignment(contractId, assignmentB.id, coordinatorHeaders);
            const confirmedB = handleApiResponse<Assignment>(confirmBRes, 200);

            expect(confirmedB.is_overtime_eligible).toBe(true);
            expect(confirmedB.provisional_cost).toBe(50.00);

            const contractCheck1Res = await apiClient.getContract(contractId, coordinatorHeaders);
            const contractCheck1 = handleApiResponse<StaffingContract>(contractCheck1Res, 200);
            expect(contractCheck1.compliance_risk_score).toBe(5);

            await apiClient.cancelAssignment(contractId, assignmentA.id, coordinatorHeaders);

            const contractCheck2Res = await apiClient.getContract(contractId, coordinatorHeaders);
            const contractCheck2 = handleApiResponse<StaffingContract>(contractCheck2Res, 200);
            expect(contractCheck2.compliance_risk_score).toBe(5);

            await apiClient.initiatePayroll(contractId, coordinatorHeaders);
            await apiClient.finalizePayroll(contractId, coordinatorHeaders);

            const finalAssignmentsRes = await apiClient.getAssignments(contractId, coordinatorHeaders);
            const finalAssignments = handleApiResponse<Assignment[]>(finalAssignmentsRes, 200, { expectPaginated: true });

            const finalAssignmentB = finalAssignments.find(a => a.id === assignmentB.id);

            expect(finalAssignmentB?.final_payout).toBe(40.00);
            expect(finalAssignmentB?.is_overtime_eligible).toBe(false);

            const finalContractRes = await apiClient.getContract(contractId, coordinatorHeaders);
            const finalContract = handleApiResponse<StaffingContract>(finalContractRes, 200);
            expect(finalContract.compliance_risk_score).toBe(0);
            expect(finalContract.budget_balance).toBe(10000 - 40.00);
        });

        it('should enforce rest period violations across different events in the same contract', async () => {
            const { contractId, staffId } = await setupBasicContract();
            const baseTime = createUnixTimestamp(24);

            const event1Res = await apiClient.createEvent(contractId, createEventPayload({ name: 'Event One' }), coordinatorHeaders);
            const event1 = handleApiResponse<Event>(event1Res, 201);
            const shift1Res = await apiClient.createShift(contractId, event1.id, createShiftPayload({ start_time: baseTime, end_time: addHours(baseTime, 8) }), coordinatorHeaders);
            const shift1 = handleApiResponse<Shift>(shift1Res, 201);

            const assign1Res = await apiClient.createAssignment(contractId, createAssignmentPayload(shift1.id, staffId), accountManagerHeaders);
            const assign1 = handleApiResponse<Assignment>(assign1Res, 201);
            await apiClient.acceptAssignment(contractId, assign1.id, buildUserHeaders('test-staff', UserRole.StaffMember));
            await apiClient.confirmAssignment(contractId, assign1.id, coordinatorHeaders);

            const event2Res = await apiClient.createEvent(contractId, createEventPayload({ name: 'Event Two' }), coordinatorHeaders);
            const event2 = handleApiResponse<Event>(event2Res, 201);
            const shift2Res = await apiClient.createShift(contractId, event2.id, createShiftPayload({ start_time: addHours(baseTime, 9), end_time: addHours(baseTime, 17) }), coordinatorHeaders);
            const shift2 = handleApiResponse<Shift>(shift2Res, 201);

            const assign2Res = await apiClient.createAssignment(contractId, createAssignmentPayload(shift2.id, staffId), accountManagerHeaders);

            validateErrorEnvelope(assign2Res, {
                expectedErrorId: ApiErrorId.ERR_REST_PERIOD_VIOLATION,
            });
        });

        it('should fail to cancel a PAID assignment', async () => {
            const { contractId, eventId, staffId } = await setupBasicContract();
            const shiftRes = await apiClient.createShift(contractId, eventId, createShiftPayload({}), coordinatorHeaders);
            const shift = handleApiResponse<Shift>(shiftRes, 201);

            const assignRes = await apiClient.createAssignment(contractId, createAssignmentPayload(shift.id, staffId), accountManagerHeaders);
            const assignment = handleApiResponse<Assignment>(assignRes, 201);

            await apiClient.acceptAssignment(contractId, assignment.id, buildUserHeaders('test-staff', UserRole.StaffMember));
            await apiClient.confirmAssignment(contractId, assignment.id, coordinatorHeaders);
            await apiClient.initiatePayroll(contractId, coordinatorHeaders);
            await apiClient.finalizePayroll(contractId, coordinatorHeaders);

            const paidAssignmentRes = await apiClient.getAssignment(contractId, assignment.id, coordinatorHeaders);
            const paidAssignment = handleApiResponse<Assignment>(paidAssignmentRes, 200);
            expect(paidAssignment.status).toBe(AssignmentStatus.PAID);

            const cancelRes = await apiClient.cancelAssignment(contractId, paidAssignment.id, coordinatorHeaders);

            validateErrorEnvelope(cancelRes, {
                expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE,
            });
        });

        it('should fail with ERR_INSUFFICIENT_BUDGET during confirmation', async () => {
            const { contractId, eventId, staffId } = await setupBasicContract(850.00, 20.00);

            const baseTime = createUnixTimestamp(24);
            const shift1Res = await apiClient.createShift(contractId, eventId, createShiftPayload({ role_name: "Late Shift", start_time: addHours(baseTime, 10), end_time: addHours(baseTime, 51) }), coordinatorHeaders);
            const shift1 = handleApiResponse<Shift>(shift1Res, 201);

            const shift2Res = await apiClient.createShift(contractId, eventId, createShiftPayload({ role_name: "Early Shift", start_time: baseTime, end_time: addHours(baseTime, 1) }), coordinatorHeaders);
            const shift2 = handleApiResponse<Shift>(shift2Res, 201);

            const assign1Res = await apiClient.createAssignment(contractId, createAssignmentPayload(shift1.id, staffId), accountManagerHeaders);
            const assign1 = handleApiResponse<Assignment>(assign1Res, 201);
            await apiClient.acceptAssignment(contractId, assign1.id, buildUserHeaders('test-staff', UserRole.StaffMember));

            const assign2Res = await apiClient.createAssignment(contractId, createAssignmentPayload(shift2.id, staffId), accountManagerHeaders);
            validateErrorEnvelope(assign2Res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
        });

        it('should fail to finalize payroll on a CLOSED contract', async () => {
            const { contractId, eventId, staffId } = await setupBasicContract();
            const shiftRes = await apiClient.createShift(contractId, eventId, createShiftPayload({}), coordinatorHeaders);
            const shift = handleApiResponse<Shift>(shiftRes, 201);
            const assignRes = await apiClient.createAssignment(contractId, createAssignmentPayload(shift.id, staffId), accountManagerHeaders);
            const assign = handleApiResponse<Assignment>(assignRes, 201);
            await apiClient.acceptAssignment(contractId, assign.id, buildUserHeaders('test-staff', UserRole.StaffMember));
            await apiClient.confirmAssignment(contractId, assign.id, coordinatorHeaders);
            await apiClient.initiatePayroll(contractId, coordinatorHeaders);
            await apiClient.finalizePayroll(contractId, coordinatorHeaders);

            const finalizeRes = await apiClient.finalizePayroll(contractId, coordinatorHeaders);
            validateErrorEnvelope(finalizeRes, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_READY_FOR_PAYROLL });
        });

        it('should fail with ERR_SHIFTS_NOT_FILLED if trying to ready an event with open shifts', async () => {
            const { contractId, eventId, staffId } = await setupBasicContract();

            const shift1Res = await apiClient.createShift(contractId, eventId, createShiftPayload({ role_name: "Filled Shift" }), coordinatorHeaders);
            const shift1 = handleApiResponse<Shift>(shift1Res, 201);
            await apiClient.createShift(contractId, eventId, createShiftPayload({ role_name: "Open Shift" }), coordinatorHeaders);

            const assignRes = await apiClient.createAssignment(contractId, createAssignmentPayload(shift1.id, staffId), accountManagerHeaders);
            const assign = handleApiResponse<Assignment>(assignRes, 201);
            await apiClient.acceptAssignment(contractId, assign.id, buildUserHeaders('test-staff', UserRole.StaffMember));
            await apiClient.confirmAssignment(contractId, assign.id, coordinatorHeaders);

            const readyRes = await apiClient.updateEventStatus(contractId, eventId, { status: EventStatus.READY_FOR_EXECUTION }, coordinatorHeaders);
            validateErrorEnvelope(readyRes, { expectedErrorId: ApiErrorId.ERR_SHIFTS_NOT_FILLED });
        });

        it('should fail rest period check even with risk override flag', async () => {
            const { contractId, eventId, staffId } = await setupBasicContract();
            const baseTime = createUnixTimestamp(24);

            const shift1Res = await apiClient.createShift(contractId, eventId, createShiftPayload({ start_time: baseTime, end_time: addHours(baseTime, 8) }), coordinatorHeaders);
            const shift1 = handleApiResponse<Shift>(shift1Res, 201);
            const assign1Res = await apiClient.createAssignment(contractId, createAssignmentPayload(shift1.id, staffId), accountManagerHeaders);
            const assign1 = handleApiResponse<Assignment>(assign1Res, 201);
            await apiClient.acceptAssignment(contractId, assign1.id, buildUserHeaders('test-staff', UserRole.StaffMember));
            await apiClient.confirmAssignment(contractId, assign1.id, coordinatorHeaders);

            const shift2Res = await apiClient.createShift(contractId, eventId, createShiftPayload({ start_time: addHours(baseTime, 9), end_time: addHours(baseTime, 15) }), coordinatorHeaders);
            const shift2 = handleApiResponse<Shift>(shift2Res, 201);

            const failedAssignRes = await apiClient.createAssignment(contractId, createAssignmentPayload(shift2.id, staffId, { override_risk_check: true }), accountManagerHeaders);

            validateErrorEnvelope(failedAssignRes, {
                expectedErrorId: ApiErrorId.ERR_REST_PERIOD_VIOLATION,
            });
        });
    });

    describe('TC-E2E-08: Payroll and State Transition Edge Cases', () => {
        it('should block payroll initiation if unresolved assignments exist', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Payroll Block Test' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            const contractId = contract.id;
            await apiClient.activateContract(contractId, coordinatorHeaders);

            const eventRes = await apiClient.createEvent(contractId, createEventPayload({ name: 'Test Event' }), coordinatorHeaders);
            const event = handleApiResponse<Event>(eventRes, 201);

            const shiftRes = await apiClient.createShift(contractId, event.id, createShiftPayload({ role_name: 'Worker' }), coordinatorHeaders);
            const shift = handleApiResponse<Shift>(shiftRes, 201);

            const staffRes = await apiClient.createStaffProfile(contractId, createStaffProfilePayload({ first_name: 'Unresolved' }), coordinatorHeaders);
            const staff = handleApiResponse<StaffProfile>(staffRes, 201);

            const assignmentRes = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift.id, staff.id),
                accountManagerHeaders
            );
            const assignment = handleApiResponse<Assignment>(assignmentRes, 201);
            await apiClient.acceptAssignment(contractId, assignment.id, buildUserHeaders('unresolved-staff', UserRole.StaffMember));

            const initiatePayrollRes = await apiClient.initiatePayroll(contractId, coordinatorHeaders);

            validateErrorEnvelope(initiatePayrollRes, {
                expectedErrorId: ApiErrorId.ERR_UNRESOLVED_ASSIGNMENTS_EXIST,
            });

            const contractCheckRes = await apiClient.getContract(contractId, coordinatorHeaders);
            const contractCheck = handleApiResponse<StaffingContract>(contractCheckRes, 200);
            expect(contractCheck.status).toBe(ContractStatus.ACTIVE);
        });

        it('should revert a READY_FOR_EXECUTION event to PLANNING if a confirmed assignment is cancelled', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Event Revert Test' }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            const contractId = contract.id;
            await apiClient.activateContract(contractId, coordinatorHeaders);

            const eventRes = await apiClient.createEvent(contractId, createEventPayload({ name: 'Main Event' }), coordinatorHeaders);
            const event = handleApiResponse<Event>(eventRes, 201);
            const eventId = event.id;

            const shift1Res = await apiClient.createShift(contractId, eventId, createShiftPayload({ role_name: 'Role 1' }), coordinatorHeaders);
            const shift1 = handleApiResponse<Shift>(shift1Res, 201);

            const shift2Res = await apiClient.createShift(contractId, eventId, createShiftPayload({ role_name: 'Role 2' }), coordinatorHeaders);
            const shift2 = handleApiResponse<Shift>(shift2Res, 201);

            const staff1Res = await apiClient.createStaffProfile(contractId, createStaffProfilePayload({ first_name: 'Staff1' }), coordinatorHeaders);
            const staff1 = handleApiResponse<StaffProfile>(staff1Res, 201);

            const staff2Res = await apiClient.createStaffProfile(contractId, createStaffProfilePayload({ first_name: 'Staff2' }), coordinatorHeaders);
            const staff2 = handleApiResponse<StaffProfile>(staff2Res, 201);

            const assign1Res = await apiClient.createAssignment(contractId, createAssignmentPayload(shift1.id, staff1.id), accountManagerHeaders);
            const assign1 = handleApiResponse<Assignment>(assign1Res, 201);
            await apiClient.acceptAssignment(contractId, assign1.id, buildUserHeaders('staff-1', UserRole.StaffMember));
            await apiClient.confirmAssignment(contractId, assign1.id, coordinatorHeaders);

            const assign2Res = await apiClient.createAssignment(contractId, createAssignmentPayload(shift2.id, staff2.id), accountManagerHeaders);
            const assign2 = handleApiResponse<Assignment>(assign2Res, 201);
            await apiClient.acceptAssignment(contractId, assign2.id, buildUserHeaders('staff-2', UserRole.StaffMember));
            await apiClient.confirmAssignment(contractId, assign2.id, coordinatorHeaders);

            await apiClient.updateEventStatus(contractId, eventId, { status: EventStatus.READY_FOR_EXECUTION }, coordinatorHeaders);
            const readyEventRes = await apiClient.getEvent(contractId, eventId, coordinatorHeaders);
            const readyEvent = handleApiResponse<Event>(readyEventRes, 200);
            expect(readyEvent.status).toBe(EventStatus.READY_FOR_EXECUTION);

            await apiClient.cancelAssignment(contractId, assign1.id, coordinatorHeaders);

            const revertedEventRes = await apiClient.getEvent(contractId, eventId, coordinatorHeaders);
            const revertedEvent = handleApiResponse<Event>(revertedEventRes, 200);
            expect(revertedEvent.status).toBe(EventStatus.PLANNING);
        });

        it('should block OT assignment when risk threshold is met and then allow it with override', async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Risk Threshold Test', total_budget: 20000 }),
                coordinatorHeaders
            );
            const contract = handleApiResponse<StaffingContract>(contractRes, 201);
            const contractId = contract.id;
            await apiClient.activateContract(contractId, coordinatorHeaders);

            const staffRes = await apiClient.createStaffProfile(contractId, createStaffProfilePayload({ base_pay_rate_per_hour: 10 }), coordinatorHeaders);
            const staff = handleApiResponse<StaffProfile>(staffRes, 201);

            const eventRes = await apiClient.createEvent(contractId, createEventPayload({ name: 'Risk Event' }), coordinatorHeaders);
            const event = handleApiResponse<Event>(eventRes, 201);

            for (let i = 0; i < 3; i++) {
                const start = createUnixTimestamp(24 + i * 58);
                const end = addHours(start, 50);
                const shiftRes = await apiClient.createShift(
                    contractId,
                    event.id,
                    createShiftPayload({ start_time: start, end_time: end }),
                    coordinatorHeaders
                );
                const otShift = handleApiResponse<Shift>(shiftRes, 201);
                const assignRes = await apiClient.createAssignment(
                    contractId,
                    createAssignmentPayload(otShift.id, staff.id),
                    accountManagerHeaders
                );
                const assignObj = handleApiResponse<Assignment>(assignRes, 201);
                await apiClient.acceptAssignment(contractId, assignObj.id, buildUserHeaders('test-staff', UserRole.StaffMember));
                await apiClient.confirmAssignment(contractId, assignObj.id, coordinatorHeaders);
            }

            const contractCheck1Res = await apiClient.getContract(contractId, coordinatorHeaders);
            const contractCheck1 = handleApiResponse<StaffingContract>(contractCheck1Res, 200);
            expect(contractCheck1.compliance_risk_score).toBe(15);

            const otStart = createUnixTimestamp(300);
            const otEnd = addHours(otStart, 50);
            const otShiftRes = await apiClient.createShift(contractId, event.id, createShiftPayload({ role_name: 'Risky OT Shift', start_time: otStart, end_time: otEnd }), coordinatorHeaders);
            const otShift = handleApiResponse<Shift>(otShiftRes, 201);

            const failedAssignRes = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(otShift.id, staff.id, { override_risk_check: false }),
                accountManagerHeaders
            );
            validateErrorEnvelope(failedAssignRes, {
                expectedErrorId: ApiErrorId.ERR_RISK_THRESHOLD_EXCEEDED,
            });

            const successfulAssignRes = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(otShift.id, staff.id, { override_risk_check: true }),
                accountManagerHeaders
            );
            const assignment = handleApiResponse<Assignment>(successfulAssignRes, 201);
            expect(assignment.is_overtime_eligible).toBe(true);
            expect(assignment.risk_override_penalty_applied).toBe(true);

            const contractCheck2Res = await apiClient.getContract(contractId, coordinatorHeaders);
            const contractCheck2 = handleApiResponse<StaffingContract>(contractCheck2Res, 200);
            expect(contractCheck2.compliance_risk_score).toBe(30);
        });
    });

    describe('TC-E2E-09: Advanced Rule Interaction Scenarios', () => {
        it('should reject an assignment proposal that violates the rest period with another proposed shift', async () => {
            const { contractId, eventId, staffId } = await setupBasicContract();
            const baseTime = createUnixTimestamp(24);

            const shift1Res = await apiClient.createShift(contractId, eventId, createShiftPayload({ start_time: baseTime, end_time: addHours(baseTime, 8) }), coordinatorHeaders);
            const shift1 = handleApiResponse<Shift>(shift1Res, 201);
            await apiClient.createAssignment(contractId, createAssignmentPayload(shift1.id, staffId), accountManagerHeaders);

            const shift2Res = await apiClient.createShift(contractId, eventId, createShiftPayload({ start_time: addHours(baseTime, 9), end_time: addHours(baseTime, 15) }), coordinatorHeaders);
            const shift2 = handleApiResponse<Shift>(shift2Res, 201);

            const failedAssignRes = await apiClient.createAssignment(contractId, createAssignmentPayload(shift2.id, staffId), accountManagerHeaders);

            validateErrorEnvelope(failedAssignRes, {
                expectedErrorId: ApiErrorId.ERR_REST_PERIOD_VIOLATION,
            });
        });

        it('should not apply override penalty when risk threshold is not breached', async () => {
            const { contractId, eventId, staffId } = await setupBasicContract();
            const shiftRes = await apiClient.createShift(contractId, eventId, createShiftPayload({}), coordinatorHeaders);
            const shift = handleApiResponse<Shift>(shiftRes, 201);

            const assignRes = await apiClient.createAssignment(
                contractId,
                createAssignmentPayload(shift.id, staffId, { override_risk_check: true }),
                accountManagerHeaders
            );
            const assignment = handleApiResponse<Assignment>(assignRes, 201);

            expect(assignment.risk_override_penalty_applied).toBe(false);

            const contractRes = await apiClient.getContract(contractId, coordinatorHeaders);
            const contract = handleApiResponse<StaffingContract>(contractRes, 200);
            expect(contract.compliance_risk_score).toBe(assignment.is_overtime_eligible ? 5 : 0);
        });
    });

    describe('TC-E2E-10: Additional Edge Case and Failure Path Tests', () => {
        it('should fail to create assignment if budget is insufficient', async () => {
            const { contractId, eventId, staffId } = await setupBasicContract(20.00, 100.00);

            const shiftRes = await apiClient.createShift(contractId, eventId, createShiftPayload({ start_time: createUnixTimestamp(24), end_time: createUnixTimestamp(25) }), coordinatorHeaders);
            const shift = handleApiResponse<Shift>(shiftRes, 201);

            const assignRes = await apiClient.createAssignment(contractId, createAssignmentPayload(shift.id, staffId), accountManagerHeaders);
            validateErrorEnvelope(assignRes, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
        });

        it('should reject cancellation of an already-cancelled event', async () => {
            const { contractId, eventId } = await setupBasicContract();

            await apiClient.updateEventStatus(contractId, eventId, { status: EventStatus.CANCELLED }, coordinatorHeaders);

            const secondCancelRes = await apiClient.updateEventStatus(contractId, eventId, { status: EventStatus.CANCELLED }, coordinatorHeaders);

            validateErrorEnvelope(secondCancelRes, { expectedErrorId: ApiErrorId.ERR_ILLEGAL_EVENT_STATE_TRANSITION });
        });

        it('should reject creating new shifts or events on a CLOSED contract', async () => {
            const { contractId, eventId, staffId } = await setupBasicContract();
            const shiftRes = await apiClient.createShift(contractId, eventId, createShiftPayload({}), coordinatorHeaders);
            const shift = handleApiResponse<Shift>(shiftRes, 201);
            const assignRes = await apiClient.createAssignment(contractId, createAssignmentPayload(shift.id, staffId), accountManagerHeaders);
            const assign = handleApiResponse<Assignment>(assignRes, 201);
            await apiClient.acceptAssignment(contractId, assign.id, buildUserHeaders('test-staff', UserRole.StaffMember));
            await apiClient.confirmAssignment(contractId, assign.id, coordinatorHeaders);
            await apiClient.initiatePayroll(contractId, coordinatorHeaders);
            await apiClient.finalizePayroll(contractId, coordinatorHeaders);

            const closedContractRes = await apiClient.getContract(contractId, coordinatorHeaders);
            const closedContract = handleApiResponse<StaffingContract>(closedContractRes, 200);
            expect(closedContract.status).toBe(ContractStatus.CLOSED);

            const newEventRes = await apiClient.createEvent(contractId, createEventPayload({ name: "Post-closure event" }), coordinatorHeaders);
            validateErrorEnvelope(newEventRes, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_ACTIVE });
        });
    });
});
